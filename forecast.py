"""forecast.py -- データの最終年度より先の外生変数を組み立てる。

【重要】このモジュールはデータしか作らない。方程式には一切触れない。

朴(2025c) は前向きシミュレーションを行っていない。結論部にこう書いてある。

  シミュレーションは、将来のシミュレーションではなく、データ期間の範囲
  （1997年度〜2023年度）で反実仮想シミュレーションとしてこれを行った。
  これによって、難しい将来の外生変数の想定を避けられるほか、過去の外生
  変数として実績値が利用できることとなった。

つまり外生112本の将来値をどう置くかは、論文の範囲外である。ここで置く想定は
すべてこちらの判断であり、著者の見解ではない。

想定（既定）
  年ダミー9本            ゼロ。将来に既知のショックは置かない
  TIME / WHMAX          式のとおり延長する（論文に式がある）
  労働力人口 LF          社人研の将来推計人口から作った japan_pop_proj_fy.csv
                        （fetch_pop.py が作る）。無ければ据え置きに落とす
  評価調整34本           ゼロ。下の「なぜゼロか」を見ること
  残差・調整項13本        ゼロ。実績に合わせるための項なので、合わせる実績が
                        ない将来では定義できない
  それ以外88本           最終年度の値を据え置く

なぜ評価調整をゼロにするか
  朴(2025c) 結論部にこうある。

    株式などのキャピタルゲインはすべて外生変数としている。これは現時点では、
    考えられる説明変数（国債金利など）を用いて回帰分析を行っても、十分な
    決定係数をもつ信頼できる関係式を構築できないためである。しかし、
    キャピタルゲインはバブル現象の駆動力であり、追究されるべき課題である。

  著者が回帰式を作れずに外生としたものを、こちらが予測できる道理はない。
  据え置くと、最終年度にたまたま生じた評価損益が毎年永久に入り続け、
  ストックとフローの整合が崩れる（政府が赤字を出し続けているのに純債務が
  減っていく、という結果になった）。そこで「将来のキャピタルゲインは
  予測しない」＝ゼロと置く。これは中立な想定であって、無風を予想している
  わけではない。

据え置きの意味について
  据え置く88本のうち、実質政府消費(GR)や実質政府投資(IR_G)は実質値なので、
  据え置きは「実質で横ばいの財政」を意味する。一方、資本移転(KTR_*)や
  経常移転(STR_*)などは名目値なので、据え置きは名目GDPが伸びるぶんだけ
  対GDP比では縮んでいくことを意味する。中立とは言い切れないので、
  分析で効いてくるものは overrides で明示的に置き直すこと。
"""
import os
import re

import pandas as pd

import parkmodel as pm

HERE = os.path.dirname(os.path.abspath(__file__))
POP_PROJ = os.path.join(HERE, "japan_pop_proj_fy.csv")

LAST = pm.last_year()        # 実績データの最終年度（fetch_ff.FY で決まる）
# TIME と WHMAX は線形なので、データの最後の2年から傾きを取って延ばす。
# 原点や係数を fetch_misc.py と二重に持たない。

# 名目のフロー（単位は十億円）。名目GDPが伸びれば一緒に伸びるのが自然なので、
# 「対名目GDP比で据え置く」扱いにできる。単位は朴(2025c) 巻末の変数表で確認した。
#   CPEN_*  年金受給権調整    D_*   固定資本減耗      KTR_*  資本移転純受取
#   NP_*    土地純購入        OTR_H その他の社会移転
#   STR_*   社会移転純受取    T_F/T_W 直接税
#
# SB2_* は入れない。変数表は単位を「十億円」としているが、実際は営業余剰を
# 部門に配分するシェアで、4部門の合計はきっかり 1.0 になる（B2_N = sB2_N * B2）。
# 対GDP比で伸ばすと合計が 1.0 を超え、営業余剰が水増しされる。実際、
# これだけを対GDP比にすると純貸出の合計が10年で47.6兆円ずれた。
# 同じ理由で NDEPSHARE_* などの保有シェア9本も据え置く。
NOMINAL_FLOWS = [
    "CPEN_F", "CPEN_H", "D_F", "D_G",
    "KTR_F", "KTR_G", "KTR_H", "KTR_N", "KTR_W",
    "NP_F", "NP_G", "NP_H", "NP_N", "OTR_H",
    "STR_F", "STR_N", "STR_W", "T_F", "T_W",
]

# 名目だが「残高」なので対GDP比にはしない外生変数。
#
# これらを名目GDPと一緒に伸ばすと、ストックとフローの整合が壊れる。政府の
# 国債純資産は NGBA_G = -(NGSHA_G + NDEPA_G + NLBDA_G + NEQUA_G + NPENA_G
# + NNFWA_G) という残差で決まる。右辺の外生残高を勝手に増やすと、赤字と
# 無関係に NGBA_G が動いてしまい、「政府が黒字も出していないのに債務が減る」
# という、評価調整を据え置いたときと同じ壊れ方をする。だから据え置く。
NOMINAL_STOCKS = ["GOLD", "NDEPA_CB", "NDEPA_G", "NEQUA_CB", "NEQUA_G",
                  "NGSHA_G", "NLBDA_G", "NPENA_CB", "NPENA_G", "NPENA_W"]

# ゼロを置く外生変数。名前で拾う。
_ZERO_PATTERNS = [
    (r"^DUM\d+$",                              "年ダミー"),
    (r"CG_",                                   "評価調整"),
    (r"^(EPSILON_|GAPNL_|STR_GAP$|YR_GAP$|SD$)", "残差・調整項"),
]


def classify(exog):
    """外生変数を扱い方ごとに分ける。何をどう置いたかを説明するために使う。"""
    out, rest = {}, list(exog)
    for pat, name in _ZERO_PATTERNS:
        hit = [v for v in rest if re.search(pat, v)]
        rest = [v for v in rest if v not in hit]
        out[name] = sorted(hit)
    out["式で延長"] = sorted(v for v in rest if v in ("TIME", "WHMAX"))
    rest = [v for v in rest if v not in ("TIME", "WHMAX")]
    out["名目フロー"] = sorted(v for v in rest if v in NOMINAL_FLOWS)
    rest = [v for v in rest if v not in NOMINAL_FLOWS]
    out["将来推計"] = sorted(v for v in rest if v == "LF" and pop_projection() is not None)
    out["据え置き"] = sorted(v for v in rest if v not in out["将来推計"])
    return out


def pop_projection():
    """社人研の推計から作った労働力人口。無ければ None。

    fetch_pop.py は「実績の最終年度の労働力率を固定」して翌年度から先を作るので、
    CSV の始まりは実績の最終年度の翌年度になる。そうでなければ、別の年度の実績を
    基準に作った古い CSV である（2024年度確報のときに作ったものが 2023年度確報に
    下げたあとも残っていて、2025年度始まりのまま 2024年度だけ補間していた。
    2025年度で 51万人ずれていた）。黙って使わず止める。"""
    if not os.path.exists(POP_PROJ):
        return None
    s = pd.read_csv(POP_PROJ, index_col=0, encoding="utf-8-sig")["LF"]
    s.index = s.index.astype(int)
    if int(s.index.min()) != LAST + 1:
        raise ValueError("japan_pop_proj_fy.csv は %d年度始まりで、実績の最終年度 %d の翌年度に"
                         "なっていない。python fetch_pop.py で作り直すこと" % (s.index.min(), LAST))
    return s


def extend(d, horizon, exog, overrides=None, nominal="hold", yn=None):
    """実績データ d を horizon 年ぶん先へ延ばした DataFrame を返す。

    d        pm.data() が返すもの（1994年度〜最終年度）
    horizon  何年先まで延ばすか
    exog     外生変数名の一覧（m.exog()）。ここに無い列は内生なので触らない
    overrides {変数名: 値 または {年度: 値}} で個別に上書きできる
    nominal  名目フロー24本の置き方。
             "hold"  最終年度の名目額のまま（対GDP比では縮んでいく）
             "gdp"   最終年度の対名目GDP比のまま。名目GDPは内生なので、
                     yn に名目GDPの経路を渡す必要がある（load() が反復で解く）
    yn       nominal="gdp" のときに使う名目GDPの系列

    内生変数の将来の行は NaN のままにしておく。sfcsim の simulate() は
    NaN を見つけると前年の値を初期値にするので、それで構わない。"""
    exog = set(exog)
    fut = list(range(LAST + 1, LAST + 1 + horizon))
    out = d.reindex(d.index.tolist() + fut)
    groups = classify(exog)
    zero = set()
    for name, _pat in [(n, p) for p, n in _ZERO_PATTERNS]:
        zero |= set(groups[name])

    for y in fut:
        for v in ("TIME", "WHMAX"):
            step = float(d[v].loc[LAST] - d[v].loc[LAST - 1])
            out.at[y, v] = float(d[v].loc[LAST]) + step * (y - LAST)
        for v in zero:
            out.at[y, v] = 0.0
        for v in groups["据え置き"]:
            out.at[y, v] = out.at[LAST, v]
        for v in groups["将来推計"]:
            proj = pop_projection()
            if y in proj.index:
                out.at[y, v] = float(proj.loc[y])
            else:                       # 推計の範囲を超えたら最後の値を伸ばす
                out.at[y, v] = float(proj.iloc[-1])
        for v in groups["名目フロー"]:
            if nominal == "gdp":
                if yn is None:
                    raise ValueError("nominal='gdp' には名目GDPの経路 yn が要ります")
                out.at[y, v] = out.at[LAST, v] * float(yn[y]) / float(yn[LAST])
            else:
                out.at[y, v] = out.at[LAST, v]
        # UNR_FLOOR は方程式のスイッチ用に足した列で、外生変数ではないが
        # 将来の行にも同じ値が要る
        if "UNR_FLOOR" in out.columns:
            out.at[y, "UNR_FLOOR"] = out.at[LAST, "UNR_FLOOR"]

    for v, val in (overrides or {}).items():
        if v not in out.columns:
            raise KeyError("%s という列がありません" % v)
        if v not in exog:
            raise ValueError("%s は内生変数です。外生変数だけ上書きできます" % v)
        if isinstance(val, dict):
            for y, x in val.items():
                out.at[y, v] = float(x)
        else:
            for y in fut:
                out.at[y, v] = float(val)
    return out


def describe(exog, nominal="hold"):
    """どの変数をどう置いたかの一覧を文字列で返す。"""
    g = classify(exog)
    lines = ["外生 %d本の将来値の置き方" % len(exog)]
    for name in ["年ダミー", "式で延長", "将来推計", "評価調整", "残差・調整項",
                 "名目フロー", "据え置き"]:
        vs = g[name]
        how = {"年ダミー": "ゼロ", "式で延長": "論文の式のとおり",
               "評価調整": "ゼロ（将来のキャピタルゲインは予測しない）",
               "残差・調整項": "ゼロ（合わせる実績がない）",
               "将来推計": "社人研の将来推計人口×労働力率（%d年度で固定）" % LAST,
               "名目フロー": {"gdp": "%d年度の対名目GDP比のまま" % LAST,
                            "hold": "%d年度の名目額のまま" % LAST}[nominal],
               "据え置き": "%d年度の値のまま" % LAST}[name]
        lines.append("  %-12s %3d本  %s" % (name, len(vs), how))
        if name not in ("据え置き",):
            lines.append("     %s" % ", ".join(vs))
    return "\n".join(lines)


def load(horizon=10, overrides=None, version=1, coeffs="reest",
         unr_floor=pm.UNR_FLOOR_DEFAULT, nominal="gdp", maxit=30, tol=1e-4,
         verbose=False, wp65=False):
    """(モデル, 将来まで延ばしたデータ, そのモデルの方程式テキスト) を返す。

    方程式テキストも一緒に返すのは、呼び出し側が「実際に解くのはこの式だ」と
    確かめられるようにするため。sanity_park.py の [0] はこれを論文の原文と
    突き合わせる。テキストを別に組み立て直すと、検証した式と解いた式が
    食い違いうる（実際そうなって一度取り逃がした）。

    nominal="gdp" のときは、名目フローを対名目GDP比で据え置く。名目GDPは
    内生なので、外生を作る -> 解く -> 名目GDPを見て外生を作り直す、を
    名目GDPの経路が動かなくなるまで繰り返す。"""
    text = pm.equations(version, coeffs, unr_floor, wp65=wp65)
    m = pm.model(version, coeffs, unr_floor, wp65=wp65)
    d = pm.data()
    if wp65:
        d = pm.wp65_residuals(d)
    if unr_floor is not None:
        d["UNR_FLOOR"] = unr_floor

    end = LAST + horizon
    ext = extend(d, horizon, m.exog(), overrides, nominal="hold")
    if nominal != "gdp":
        return m, ext, text

    yn = None
    for it in range(maxit):
        sim = m.simulate(ext, 1997, end, mode="dynamic", maxit=5000, tol=1e-7)
        new_yn = sim["YN"]
        if yn is not None:
            gap = float((new_yn.loc[LAST + 1:end] / yn.loc[LAST + 1:end] - 1)
                        .abs().max())
            if verbose:
                print("   反復 %2d 回目  名目GDPの動き %.2e" % (it + 1, gap))
            if gap < tol:
                break
        yn = new_yn
        ext = extend(d, horizon, m.exog(), overrides, nominal="gdp", yn=yn)
    else:
        raise RuntimeError("名目フローの対GDP比が %d 回で収束しませんでした" % maxit)
    return m, ext, text
