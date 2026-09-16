"""fetch_misc.py -- 残りの外生変数（ダミー・トレンド・SNA以外の統計）を作る。

朴(2025c) の外生変数のうち、資金循環と制度部門別勘定で埋まらないものを集める。

  ダミー変数と TIME                 コードで生成する
  W_HOURS                           総実労働時間指数（毎月勤労統計、30人以上、2020=100）
  WHMAX                             W_HOURS の長期トレンド（TIME に回帰した当てはめ値）
  LOAD                              製造工業稼働率指数（経済産業省、2020=100）
  CONTAX                            消費税率（年度平均）。コードで生成する
  NEER                              名目実効為替レート（日本銀行）
  YR_W                              世界の実質GDP（IMF WEO 2024年10月版の成長率から。届かなければ世界銀行）
  PM                                輸入デフレータ（内閣府 国民経済計算の確報）
  PW                                PM * NEER（本体 4.6）
  GOLD                              資金循環データから
  RH                                現金・HPM の利回り。既定はゼロ（本体 4.1）
  I_US                              米国長期金利（FRED）
  LF                                労働力人口（労働力調査）
  N_W                               外国人純就業者数（下記のとおり導出）

TIME について
  変数表は「タイムトレンド 1994cy=1」としているので TIME = 年度 - 1993。裏づけとして、毎月勤労統計の
  総実労働時間指数（30人以上）を 1994-2023年度で TIME に回帰すると
  118.47 - 0.585*TIME となり、論文の W_HOURS = 118.441954 - 0.586040*TIME と
  小数2桁まで一致する（原点を 1994 = 0 にすると定数項が 117.9 にずれる）。

W_HOURS と LOAD について
  生産関数 LOG(YR) = c + a*LOG(KN_G/PY) + b*LOG(W_HOURS*N_N) + c*LOG(LOAD*KN_N/PY)
  の推定に使う（本体 4.6）。モデルの式に入るのは、W_HOURS のトレンド WHMAX と
  LOAD の過去最大値だけである。
  W_HOURS は e-Stat の毎月勤労統計「指数累積データ」（CSV）から、調査産業計・
  事業所規模30人以上・就業形態計の月次指数を年度平均する。LOAD は統計ダッシュ
  ボードの API（キー不要）から 2020年基準の月次原指数を取って年度平均する。

YR_W について
  論文は IMF World Economic Outlook 2024年10月版の世界実質GDP成長率を使う。
  同じ版の世界集計が DBnomics（api.db.nomics.world）に保管されているので、
  そこから取る（IMF WEOAGG:2024-10 の 001.NGDP_RPCH）。届かなければ IMF の
  DataMapper（最新版）、それも駄目なら世界銀行の購買力平価ベース系列
  （NY.GDP.MKTP.PP.KD）で代用する。IMF の世界計は PPP ウェイトなので、世界銀行
  でも PPP 系列なら 2010年代の成長率が IMF と 0.2%pt 以内で揃う。市場レート
  ベース（NY.GDP.MKTP.KD）は新興国のウェイトが小さく、毎年 0.3〜0.7%pt 低く出る。
  実行環境から www.imf.org / api.db.nomics.world に出られる必要がある。

N_W について
  変数表は出典を「労働力調査」としているが、外国人純就業者数はそのままの系列
  としては公表されていない。論文自身が W = WB_N/N_N = WB_W/N_W という関係を
  置いている（本体 4.6）ので、そこから N_W = WB_W * N_N / WB_N として求める。

出力: japan_misc_fy.csv
"""
import io
import json
import os
import re
import sys
import time

import numpy as np
import pandas as pd
import requests

import fetch_sector as fs
from fetch_ff import FY          # 確報の対象年度は fetch_ff が持つ

HERE = os.path.dirname(os.path.abspath(__file__))
TIME_ORIGIN = 1993               # TIME = 年度 - TIME_ORIGIN（変数表: 1994cy = 1）
DUMMIES = [2000, 2001, 2007, 2008, 2009, 2014, 2020, 2022, 2023]
# 論文の労働時間トレンド（本体 4.6、WP65 付録）。いまは自前で推定し、これは
# 突き合わせの参考値として持つ
PAPER_WHMAX_C, PAPER_WHMAX_T = 118.441954023, -0.586040044494

# 毎月勤労統計「指数累積データ」（e-Stat のファイル、CSV、キー不要）
HOURS_URL = ("https://www.e-stat.go.jp/stat-search/file-download"
             "?statInfId=000032189777&fileKind=1")
HOURS_CACHE = os.path.join(HERE, "cache", "maikin_index_cumulative.csv")
HOURS_SIZE = "T"                 # 事業所規模のコード。T = 30人以上（下の docstring）

# 製造工業稼働率指数 2020年基準（統計ダッシュボード API、キー不要）
LOAD_CODE = "0502070306000090010"
LOAD_CACHE = os.path.join(HERE, "cache", "dashboard_load_2020_monthly.json")

# 労働力調査 長期時系列表 表2-2「主要項目（年度平均結果）」。総務省統計局が
# e-Stat にファイルとして置いている Excel で、API キー無しで取れる。
# e-Stat API（キー必須）の年度別の表（statsDataId 0002060065）は各年の報告書の値の
# ままで、2010〜2012年度が震災で欠測なので使わない。長期時系列表は国勢調査基準の
# 切替えに合わせた時系列接続用数値（2005〜2021年度）と震災期の補完推計値を載せて
# おり、論文が出典に挙げているのもこの表である。
LABOUR_URL = ("https://www.e-stat.go.jp/stat-search/file-download"
              "?statInfId=000040104500&fileKind=0")
LABOUR_CACHE = os.path.join(HERE, "cache", "roudou_longtime_2-2_fy.xlsx")


def read_local(name, cols=None):
    p = os.path.join(HERE, name)
    d = pd.read_csv(p, index_col=0, encoding="utf-8-sig")
    d.index = d.index.astype(int)
    return d[cols] if cols else d


ESRI = "https://www.esri.cao.go.jp"


def fetch_neer():
    """名目実効為替レート（日本銀行 FM09/FX180110001、月次）を年度平均にする。

    数値が大きいほど円高。論文は1を基準とする指数を使うので、
    呼び出し側で100で割ること（本体・WP65 4.3）。"""
    r = requests.get("https://www.stat-search.boj.or.jp/api/v1/getDataCode",
                     params={"db": "FM09", "code": "FX180110001",
                             "startDate": "199304", "lang": "jp"},
                     headers={"Accept-Encoding": "gzip"}, timeout=60).json()
    v = r["RESULTSET"][0]["VALUES"]
    m = pd.Series(pd.to_numeric(pd.Series(v["VALUES"]), errors="coerce").values,
                  index=v["SURVEY_DATES"])
    out = {}
    for ym, val in m.items():
        y, mth = divmod(int(ym), 100)
        out.setdefault(y if mth >= 4 else y - 1, []).append(val)
    s = pd.Series({fy: np.nanmean(vs) for fy, vs in out.items()
                   if len(vs) >= 6}).sort_index()
    s.index.name = "年度"
    return s


# 世界の実質GDP成長率。論文の出典は IMF World Economic Outlook 2024年10月版。
# DBnomics（IMF のデータを版ごとに保管しているミラー）に同じ版の世界集計がある。
WEO_VINTAGE = "2024-10"
WEO_URL = ("https://api.db.nomics.world/v22/series/IMF/WEOAGG:%s/"
           "001.NGDP_RPCH.pcent_change?observations=1" % WEO_VINTAGE)
WEO_CACHE = os.path.join(HERE, "cache", "weo_%s_world_growth.json" % WEO_VINTAGE)


def _weo_world_growth():
    """IMF WEO 2024年10月版の世界実質GDP成長率（暦年、％）を {年: 値} で返す。

    取れる順に (1) DBnomics の WEOAGG:2024-10（論文と同じ版）、(2) IMF DataMapper
    の WEOWORLD（最新版。版が違う）を試し、どれで取れたかを2つめの返り値で返す。
    どちらも届かなければ None。"""
    if os.path.exists(WEO_CACHE):
        j = json.load(io.open(WEO_CACHE, encoding="utf-8"))
        return {int(k): float(v) for k, v in j["values"].items()}, j["source"]
    tries = [
        ("IMF WEO %s（DBnomics）" % WEO_VINTAGE, WEO_URL,
         lambda j: dict(zip(j["series"]["docs"][0]["period"], j["series"]["docs"][0]["value"]))),
        ("IMF WEO 最新版（DataMapper）",
         "https://www.imf.org/external/datamapper/api/v1/NGDP_RPCH/WEOWORLD",
         lambda j: j["values"]["NGDP_RPCH"]["WEOWORLD"]),
    ]
    for name, url, pick in tries:
        try:
            r = requests.get(url, timeout=90)
            r.raise_for_status()
            raw = pick(r.json())
        except Exception as ex:
            print("   %s は取れなかった (%s)" % (name, str(ex)[:60]))
            continue
        vals = {int(str(k)[:4]): float(v) for k, v in raw.items() if v is not None}
        if len(vals) < 30:
            print("   %s は %d 年ぶんしかない" % (name, len(vals)))
            continue
        os.makedirs(os.path.dirname(WEO_CACHE), exist_ok=True)
        json.dump({"source": name, "values": vals}, io.open(WEO_CACHE, "w", encoding="utf-8"))
        return vals, name
    return None, None


def fetch_world_gdp():
    """世界の実質GDP指数 YR_W（年度、1994年＝100）。

    論文（本体 4.6）は IMF WEO 2024年10月版の世界実質GDP成長率から 1994年＝100 の
    レベル指数を作る。ここも同じ版の成長率（DBnomics 経由）で作り、暦年→年度は
    朴(2025c) 脚注1と同じ 3:1 の加重で変換する。IMF に届かないときは世界銀行の
    購買力平価ベース系列（NY.GDP.MKTP.PP.KD、IMF と同じ PPP ウェイト）で代用する。"""
    growth, src = _weo_world_growth()
    if growth is not None:
        years = sorted(y for y in growth if y >= 1993)
        level = {}
        cy = pd.Series(dtype=float)
        lv = 100.0
        level[years[0] - 1] = lv
        for y in years:
            lv = lv * (1 + growth[y] / 100.0)
            level[y] = lv
        cy = pd.Series(level).sort_index()
        cy = cy / cy.loc[1994] * 100.0
        print("   YR_W の出典: %s" % src)
    else:
        j = requests.get("https://api.worldbank.org/v2/country/WLD/indicator/"
                         "NY.GDP.MKTP.PP.KD",
                         params={"format": "json", "per_page": "200"},
                         timeout=60).json()[1]
        cy = pd.Series({int(o["date"]): o["value"] for o in j
                        if o["value"] is not None}).sort_index()
        cy = cy / cy.loc[1994] * 100.0
        print("   YR_W の出典: 世界銀行 NY.GDP.MKTP.PP.KD（IMF に届かなかったので代用）")
    # 暦年→年度： t年を3、t+1年を1の重みで加重平均（朴(2025c) 脚注1と同じ方法）
    fy = pd.Series(dict((y, (3 * cy[y] + cy[y + 1]) / 4)
                        for y in cy.index if y + 1 in cy.index)).sort_index()
    s = fy / fy.loc[1994] * 100.0
    s.index.name = "年度"
    return s

def fetch_pm():
    """輸入デフレータ（内閣府 国民経済計算の確報、指数）。

    四半期別GDP速報（QE）の年度デフレーターは基準年が確報と揃うとは限らない
    （2023年度確報は 2015年度=100、QE は 2020年度=100）。混ぜると PW を通じて
    PM が13%ずれる（ファイナルテストの PM の誤差率が 0.01% から 13.43% に跳ねる）
    ので、確報から取る。

    PM の実績は fetch_endo.py が確報から作っている。PW はその逆算なので、
    同じ確報・同じ基準年から取るのが正しい。外部依存も1つ減る。"""
    defl = fs.read_sna("%dffm1dn_jp.xlsx" % FY, "実数")
    return fs.pick(defl, "（２）（控除）財貨・サービスの輸入")


def _fy_mean(monthly):
    """{YYYYMM: 値} を年度平均にする。12か月そろった年度だけ返す。"""
    acc = {}
    for ym, v in monthly.items():
        y, m = int(str(ym)[:4]), int(str(ym)[4:6])
        acc.setdefault(y if m >= 4 else y - 1, []).append(float(v))
    s = pd.Series({fy: np.mean(vs) for fy, vs in acc.items() if len(vs) == 12})
    s = s.sort_index()
    s.index.name = "年度"
    return s


def fetch_hours():
    """総実労働時間指数 W_HOURS（毎月勤労統計、調査産業計、事業所規模30人以上、
    就業形態計、2020=100）を年度平均で返す。

    e-Stat の「指数累積データ」CSV を読む。列は見出しで選ぶ。規模のコードは
    0 と T の2つで、T が30人以上。根拠は、T を 1994-2023年度で TIME に回帰すると
    118.47 - 0.585*TIME となって論文の W_HOURS の式（118.44 - 0.586*TIME）と
    一致すること（0 だと 113.2 - 0.37*TIME で合わない）。"""
    if os.path.exists(HOURS_CACHE):
        raw = io.open(HOURS_CACHE, "rb").read()
    else:
        r = requests.get(HOURS_URL, timeout=300)
        r.raise_for_status()
        raw = r.content
        os.makedirs(os.path.dirname(HOURS_CACHE), exist_ok=True)
        io.open(HOURS_CACHE, "wb").write(raw)
    d = pd.read_csv(io.BytesIO(raw), encoding="cp932", dtype=str)
    d.columns = [c.strip() for c in d.columns]
    for c in ("種別", "年", "月", "産業分類", "規模", "就業形態", "総実労働時間"):
        if c not in d.columns:
            raise ValueError("指数累積データに列「%s」がありません" % c)
        d[c] = d[c].astype(str).str.strip()
    x = d[(d["種別"] == "指数") & (d["産業分類"] == "TL") & (d["就業形態"] == "0")
          & (d["規模"] == HOURS_SIZE) & (d["月"] != "CY")]
    if x.empty:
        raise ValueError("指数累積データに 調査産業計・規模%s の月次指数がありません" % HOURS_SIZE)
    monthly = {y + m: v for y, m, v in zip(x["年"], x["月"], pd.to_numeric(x["総実労働時間"], errors="coerce"))
               if pd.notna(v)}
    return _fy_mean(monthly)


def fetch_load():
    """製造工業稼働率指数 LOAD（経済産業省、2020年基準、原指数）を年度平均で返す。

    統計ダッシュボードの API から月次原指数を取る（キー不要）。2020年基準の
    系列は 1978年1月まで接続されている。"""
    if os.path.exists(LOAD_CACHE):
        monthly = json.load(io.open(LOAD_CACHE, encoding="utf-8"))
    else:
        r = requests.get("https://dashboard.e-stat.go.jp/api/1.0/Json/getData",
                         params={"Lang": "JP", "IndicatorCode": LOAD_CODE, "Cycle": "1",
                                 "RegionalRank": "2", "IsSeasonalAdjustment": "1"},
                         timeout=180)
        r.raise_for_status()
        objs = r.json()["GET_STATS"]["STATISTICAL_DATA"]["DATA_INF"]["DATA_OBJ"]
        monthly = {o["VALUE"]["@time"][:6]: float(o["VALUE"]["$"]) for o in objs}
        if len(monthly) < 300:
            raise ValueError("稼働率指数が %d か月ぶんしか取れませんでした" % len(monthly))
        os.makedirs(os.path.dirname(LOAD_CACHE), exist_ok=True)
        json.dump(monthly, io.open(LOAD_CACHE, "w", encoding="utf-8"))
    return _fy_mean(monthly)


def hours_trend(hours, years):
    """W_HOURS を TIME に回帰して WHMAX の係数を返す（本体 4.6 と同じ OLS）。"""
    t = np.array([y - TIME_ORIGIN for y in years], dtype=float)
    h = hours.reindex(years).astype(float).values
    if np.isnan(h).any():
        raise ValueError("W_HOURS に欠測があります: %s" % [y for y, v in zip(years, h) if np.isnan(v)])
    slope, const = np.polyfit(t, h, 1)
    return const, slope


def contax(fy):
    """消費税率（年度平均、％）。1997年4月に5%、2014年4月に8%、2019年10月に10%。"""
    if fy <= 1996:
        return 3.0
    if fy <= 2013:
        return 5.0
    if fy <= 2018:
        return 8.0
    if fy == 2019:
        return 9.0          # 10月引き上げなので年度平均で9%
    return 10.0


def fetch_i_us():
    """米国長期金利（10年国債利回り、月次）を年度平均にする。"""
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=IRLTLT01USM156N"
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=90)
            r.raise_for_status()
            break
        except Exception as ex:
            if attempt == 3:
                raise
            print("   再試行 FRED (%s)" % str(ex)[:50])
            time.sleep(2 ** attempt)
    d = pd.read_csv(io.StringIO(r.text))
    d.columns = ["date", "v"]
    d["date"] = pd.to_datetime(d["date"])
    d["v"] = pd.to_numeric(d["v"], errors="coerce")
    fy = d["date"].dt.year - (d["date"].dt.month < 4).astype(int)
    s = d.groupby(fy)["v"].mean() / 100.0        # ％ -> 小数
    s.index.name = "年度"
    return s


def _labour_col(d, label, rows):
    """見出し行の中で label と一致する最初の列（男女計の欄）を返す。"""
    hits = [c for r in rows for c in range(d.shape[1])
            if str(d.iat[r, c]).strip() == label]
    if not hits:
        raise ValueError("長期時系列表に見出し「%s」がありません" % label)
    return min(hits)


def fetch_labour():
    """労働力調査 長期時系列表（年度平均、全国、万人）から
    労働力人口 LF・就業者 EMP・完全失業者 UN を取る。

    列は見出しの文字（労働力人口・就業者・完全失業者）から探す。男女計が左、
    男・女が右に並ぶので、それぞれ最初に出る列を取る。年度の列は西暦が
    数字で入っている列を探す。
    2010・2011年度は東日本大震災で岩手・宮城・福島の調査ができず、表には
    補完推計値が載っている（注記シート）。値の無い年度があれば線形補間で
    埋め、埋めた年度を呼び出し側に返す。"""
    if os.path.exists(LABOUR_CACHE):
        raw = io.open(LABOUR_CACHE, "rb").read()
    else:
        r = requests.get(LABOUR_URL, timeout=120)
        r.raise_for_status()
        raw = r.content
        os.makedirs(os.path.dirname(LABOUR_CACHE), exist_ok=True)
        io.open(LABOUR_CACHE, "wb").write(raw)
    d = pd.read_excel(io.BytesIO(raw), sheet_name=0, header=None)

    # 別の表を掴んでいたらここで止まる
    head = " ".join(str(v) for v in d.iloc[:6].values.ravel() if pd.notna(v))
    for must in ("年度平均", "(万人)"):
        if must not in head:
            raise ValueError("長期時系列表の表題に「%s」がありません" % must)
    hdr = range(0, 12)
    c_lf, c_emp, c_un = (_labour_col(d, k, hdr)
                         for k in ("労働力人口", "就業者", "完全失業者"))
    c_male = _labour_col(d, "男", hdr)
    if not (c_lf < c_emp < c_un < c_male):
        raise ValueError("長期時系列表の列の並びが想定と違います "
                         "(LF %d, 就業者 %d, 完全失業者 %d, 男 %d)"
                         % (c_lf, c_emp, c_un, c_male))
    c_year = None
    for c in range(d.shape[1]):
        v = pd.to_numeric(d[c], errors="coerce")
        if ((v >= 1953) & (v <= 2100)).sum() >= 50:
            c_year = c
            break
    if c_year is None:
        raise ValueError("長期時系列表に西暦の列がありません")

    yr = pd.to_numeric(d[c_year], errors="coerce")
    body = d[yr.notna()]
    out = pd.DataFrame({
        "LF": pd.to_numeric(body[c_lf], errors="coerce").values,
        "EMP": pd.to_numeric(body[c_emp], errors="coerce").values,
        "UN": pd.to_numeric(body[c_un], errors="coerce").values,
    }, index=yr[yr.notna()].astype(int).values)
    out.index.name = "年度"
    # Excel の値は整数で入ってくる。整数のまま CSV に書くと、読み込んだ側で
    # int64 の列になり、モデルが小数を代入したときに pandas が型を理由に止まる
    out = out.astype(float)
    # 1973年度は沖縄県を含まない行と含む行の2行がある（沖縄の本土復帰は
    # 1972年7月）。後の行（沖縄を含む）を採る。それ以外に同じ年度が2行あれば
    # 表の組み方が変わっているので止める
    dups = sorted(set(out.index[out.index.duplicated()]))
    if dups and dups != [1973]:
        raise ValueError("長期時系列表に同じ年度が2行あります: %s" % dups)
    out = out[~out.index.duplicated(keep="last")]
    out = out.reindex(range(out.index.min(), out.index.max() + 1))
    filled = out.index[out["LF"].isna()].tolist()
    out = out.interpolate(method="index", limit_area="inside")
    # モデルの期間について 就業者 + 完全失業者 = 労働力人口 を検算する
    # （各項目を万人に丸めているので ±2万人まで許す）
    span = out.loc[1994:FY]
    gap = (span["EMP"] + span["UN"] - span["LF"]).abs().max()
    if gap > 2.0:
        raise ValueError("労働力人口 ≠ 就業者 + 完全失業者（最大 %.0f 万人）" % gap)
    return out, [y for y in filled if 1994 <= y <= FY]

def main():
    print("=" * 74)
    print("残りの外生変数（ダミー・トレンド・SNA以外の統計）")
    print("=" * 74)
    fail = []

    ff = read_local("japan_ff_stock_fy.csv")
    a1_years = ff.index

    out = pd.DataFrame(index=a1_years)
    out.index.name = "年度"

    print("\n[1] ダミー変数とトレンド")
    for y in DUMMIES:
        out["DUM%d" % y] = (out.index == y).astype(float)
    out["TIME"] = out.index - TIME_ORIGIN
    print("   ダミー %d 本 / TIME = 年度 - %d（1994年度 = %d）"
          % (len(DUMMIES), TIME_ORIGIN, 1994 - TIME_ORIGIN))

    print("\n[1b] 労働時間と稼働率（生産関数の推定に使う）")
    hours = fetch_hours()
    out["W_HOURS"] = hours
    c0, c1 = hours_trend(hours, list(range(1994, FY + 1)))
    out["WHMAX"] = c0 + c1 * out["TIME"]
    print("   W_HOURS（総実労働時間指数, 30人以上）1994年度 %.1f → %d年度 %.1f"
          % (hours.loc[1994], FY, hours.loc[FY]))
    print("   WHMAX = %.3f %+.4f*TIME（1994-%d年度の OLS）  論文 %.3f %+.4f*TIME"
          % (c0, c1, FY, PAPER_WHMAX_C, PAPER_WHMAX_T))
    load = fetch_load()
    out["LOAD"] = load
    print("   LOAD（製造工業稼働率指数 2020=100）1994年度 %.1f → %d年度 %.1f / 1994年度以降の最大 %.2f（%d年度）  論文の LOADmax 135.6667"
          % (load.loc[1994], FY, load.loc[FY], load.loc[1994:FY].max(), int(load.loc[1994:FY].idxmax())))

    print("\n[2] 資金循環から")
    # 各部門の純 GSH を足すと、負債の裏付けが無い貨幣用金だけが残る（本体 表9 の注）
    out["GOLD"] = sum(ff["NGSHA_%s" % s] for s in ["N", "CB", "F", "G", "H", "W"])
    print("   GOLD（貨幣用金）最終年度 %.1f 十億円" % out["GOLD"].iloc[-1])

    print("\n[3] 為替・世界需要・消費税率")
    out["CONTAX"] = [contax(y) for y in out.index]
    # NEER は論文では1を基準とする指数（本体・WP65 4.3）。日銀の系列は
    # 2020年=100 なので100で割る。WP65 のシナリオ3が「20%ポイント高く」＝
    # +0.2 と書いているので、基準を合わせておかないとショックの大きさがずれる。
    out["NEER"] = fetch_neer() / 100.0
    out["YR_W"] = fetch_world_gdp()
    # PW は PM = PW/NEER の逆算（本体 4.6）。論文のデフレータは100基準ではなく
    # 1基準なので、指数（2020年度=100）を100で割ってから使う。ここを取り違えると
    # PM が100倍になり、モデル全体が壊れる。
    out["PW"] = fetch_pm() / 100.0 * out["NEER"]
    out["RH"] = 0.0                               # 現金・HPM には利子を付けない（本体 4.1）
    print("   CONTAX（最終年度 %.0f%%）/ NEER（同 %.3f）/ YR_W（同 %.1f）/ PW（同 %.4f）/ RH"
          % (out["CONTAX"].iloc[-1], out["NEER"].iloc[-1],
             out["YR_W"].iloc[-1], out["PW"].iloc[-1]))

    print("\n[4] 外部の統計")
    out["I_US"] = fetch_i_us()
    print("   I_US（米国長期金利, FRED）最終年度 %.4f" % out["I_US"].iloc[-1])
    lab, filled = fetch_labour()
    out["LF"] = lab["LF"]
    print("   LF（労働力人口, 労働力調査）最終年度 %.0f 万人" % out["LF"].iloc[-1])
    if filled:
        print("   ※ %s年度は東日本大震災で調査が欠測。線形補間で埋めた" % filled)

    print("\n[5] 外国人純就業者数 N_W")
    # W = WB_N/N_N = WB_W/N_W より N_W = WB_W * N_N / WB_N（本体 4.6）
    # ファイル名の年度は FY から作る（直書きすると版を変えたとき別の版を読む）
    a1 = fs.read_sna("%da1_jp.xlsx" % FY, "年度")
    row = fs.read_sna("%da4_jp.xlsx" % FY, "年度（１）経常")
    wb_n = a1["雇用者報酬"]
    wb_w = fs.pick(row, "雇用者報酬（受取）") - fs.pick(row, "雇用者報酬（支払）")
    # N_N は論文と同じく労働力調査の就業者数（本体 4.1）
    out["N_W"] = wb_w * lab["EMP"] / wb_n
    print("   N_W 最終年度 %.1f 万人（賃金率が内外で等しいという仮定から導出）"
          % out["N_W"].iloc[-1])

    print("\n[6] 検算")
    miss = [c for c in out.columns if out[c].isna().any()]
    for c in miss:
        yrs = out.index[out[c].isna()].tolist()
        print("   欠測 %-8s %d年度分 %s" % (c, len(yrs), yrs[:8]))
    print("   全系列に欠測が無いか: %s" % ("OK" if not miss else "欠測あり"))
    if miss:
        # 欠測入りの CSV を書くと、後続の fetch_*.py と park_check.py が
        # それを読んでしまう。前回の正常な CSV を残したまま失敗で止める。
        fail.append("欠測: " + ", ".join(miss))

    if not fail:
        out.round(6).to_csv("japan_misc_fy.csv", encoding="utf-8-sig")
        print("\n   japan_misc_fy.csv  %d年度 × %d系列 (%d-%d)"
              % (len(out), out.shape[1], out.index.min(), out.index.max()))
    print("=" * 74)
    if fail:
        print("失敗:", ", ".join(fail))
        print("   japan_misc_fy.csv は書き換えていない")
        return 1
    print("完了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
