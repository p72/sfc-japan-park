"""fetch_ff.py -- 資金循環（金融資産・負債）のデータセットを作る。

朴(2025c) は国民経済計算の金融資産49品目・8部門を、金融資産種別7種・6部門に
統合したデータセットを Excel の VBA で作っている（本体 2章、表1・表2）。
ここでは同じものを、ESRI が公表している確報の Excel から直接組み立てる。

使う統計表（内閣府「国民経済計算年次推計」確報）:
  24．金融資産・負債の取引  総括表 / 金融機関の内訳   ← フロー
  6．金融資産・負債の残高    総括表 / 金融機関の内訳   ← ストック

いずれも年度ごとにシートが分かれている（平成6年度から1シートずつ。列が部門、
行が金融資産・負債の項目）ので、全年度を一枚に均す。

【表の組み方は確報の版で違う】
  総括表        どの版も 81行×23列。資産側が左、負債側が右に並ぶ（+11列）
  金融機関の内訳  2024年度確報は 1シート 81行×21列に資産側と負債側が左右に並ぶ。
                2023年度確報は資産側（ss62 / s242）と負債側（ss63 / s243）が
                **別ファイル**で、それぞれ 80行×29列（部門の内訳が細かい）。
  列は数えて決め打ちせず、見出し行の「中央銀行」の位置から探す。番号で決め打ちすると
  日銀の負債側に別の列を当てて、日銀と他金融機関の残高・取引が全部ずれたことがある。

評価調整（キャピタルゲイン）は統計として存在しないので、論文と同じ

    評価調整_t = 残高_t - 残高_{t-1} - 取引_t

で計算する。ストックとフローの両方を取るのはこのため。

出力:
  japan_ff_stock_fy.csv   各部門・各資産の純残高（資産-負債）
  japan_ff_flow_fy.csv    同・純取引
  japan_ff_cg_fy.csv      同・評価調整
"""
import io
import os
import re
import sys
import time

import pandas as pd
import requests

FY = 2023                        # 確報の対象年度。ここがデータセットの版を決める。
#
# 朴(2025c)/(2026a)/(2026) WP65 はいずれも「2023年度国民経済計算」を使っている。
# 論文とデータの版まで揃えている。
# 上げ下げするときは、このリポジトリのすべての数字を作り直して照合し直すこと
# （AGENTS.md の「数字を報告するときの作法」）。
BASE = ("https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/"
        "%d/tables/" % FY)
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")

FILES = {                        # 用途 -> ファイル名
    "flow_sum":  "%ds241_jp.xlsx" % FY,      # 取引・総括表
    "flow_fin":  "%ds242_jp.xlsx" % FY,      # 取引・金融機関の内訳
    "stock_sum": "%dss61_jp.xlsx" % FY,      # 残高・総括表
    "stock_fin": "%dss62_jp.xlsx" % FY,      # 残高・金融機関の内訳
    # 内訳表が資産側と負債側で別ファイルになっている版（2023年度確報）のみ使う。
    # 見出しに「中央銀行」が1つしか無いときだけ取りに行く。
    "flow_fin_liab":  "%ds243_jp.xlsx" % FY,
    "stock_fin_liab": "%dss63_jp.xlsx" % FY,
}

# ---- 総括表の列。資産側がここ、負債側は +11 -------------------------------
COL = {"NFC": 1, "FIN": 4, "G": 7, "H": 8, "NPISH": 9, "W": 10, "SUM": 11}
LIAB_OFFSET = 11
# 見出し行（5〜6行目）にこの並びで部門名が入っていることを毎回確かめる。
# 列の並びが版で変わっても黙って読まないため。
_SUMMARY_HEADER = {1: "非金融法人企業", 4: "金融機関", 7: "一般政府", 8: "家計",
                   9: "対家計民間", 10: "海外", 11: "合計"}
# 金融機関の内訳は「中央銀行」の列だけ使う。位置は見出しから探す（_cb_columns）。
CB_LABEL = "中央銀行"

TYPES = ["GSH", "GB", "DEP", "LBD", "EQU", "PEN"]
SECTORS = ["N", "CB", "F", "G", "H", "W"]

_ERA = {"明治": 1867, "大正": 1911, "昭和": 1925, "平成": 1988, "令和": 2018}
_KANSUJI = {"元": 1, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
            "六": 6, "七": 7, "八": 8, "九": 9}


def sheet_year(name):
    """'平成６' や '令和元' を西暦の年度に直す。"""
    name = name.strip()
    for era, base in _ERA.items():
        if name.startswith(era):
            rest = name[len(era):]
            rest = rest.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
            if rest.isdigit():
                n = int(rest)
            else:                                   # 十の位を含む漢数字
                n = 0
                if "十" in rest:
                    a, _, b = rest.partition("十")
                    n = (_KANSUJI.get(a, 1) if a else 1) * 10 + (_KANSUJI.get(b, 0) if b else 0)
                else:
                    n = _KANSUJI.get(rest, 0)
            return base + n
    raise ValueError("年号を解釈できません: %r" % name)


def fetch(fname):
    """Excel を取ってくる。一度落としたものは cache/ に残して使い回す。"""
    path = os.path.join(CACHE, fname)
    if os.path.exists(path):
        return path
    if not os.path.isdir(CACHE):
        os.makedirs(CACHE)
    url = BASE + fname
    for attempt in range(4):
        try:
            r = requests.get(url, timeout=90)
            r.raise_for_status()
            with open(path, "wb") as fh:
                fh.write(r.content)
            print("   取得 %s (%.0f KB)" % (fname, len(r.content) / 1024.0))
            return path
        except Exception as ex:
            if attempt == 3:
                raise
            print("   再試行 %s (%s)" % (fname, str(ex)[:60]))
            time.sleep(2 ** attempt)


def _norm(s):
    s = "" if pd.isna(s) else str(s)
    return re.sub(r"\s|　", "", s).replace("（", "(").replace("）", ")")


def _rowmap(df):
    m = {}
    for i in range(len(df)):
        k = _norm(df.iat[i, 0])
        if k and k not in m:
            m[k] = i
    return m


def _num(df, i, c):
    v = df.iat[i, c]
    if pd.isna(v):
        return 0.0
    if isinstance(v, str):
        v = v.replace(",", "").strip()
        if v in ("-", "－", ""):
            return 0.0
    try:
        return float(v)
    except ValueError:
        return 0.0


def aggregate(df, rows, col):
    """1部門1列ぶんを、49品目から資産種別6種に統合する。

    朴(2025c) 表1 の統合。表1 の「融資・債券・デリバティブ」の欄は
    債務証券の内訳しか載っていないが、貸出・借入と金融派生商品、
    その他をここに入れないと部門の合計が原表と合わない。実際に
    合計が一致することを check() で毎回確認している。"""
    def v(key):
        return _num(df, rows[key], col)
    hpm = v("(1)現金") + v("(2)日銀預け金") + v("(3)政府預金")
    gb = v("(1)国庫短期証券") + v("(2)国債・財投債")
    return {
        "GSH": v("1.貨幣用金・ＳＤＲ") + hpm,
        "DEP": v("2.現金・預金") - hpm,
        "GB":  gb,
        "LBD": (v("3.貸出・借入") + (v("4.債務証券") - gb)
                + v("7.金融派生商品・雇用者ストックオプション")
                + v("8.その他の金融資産・負債")),
        "EQU": v("5.持分・投資信託受益証券"),
        "PEN": v("6.保険・年金・定型保証"),
    }


def _header_cells(df, rows=(4, 5, 6, 7)):
    """見出し行の (行, 列) -> 文字列。"""
    out = {}
    for i in rows:
        for j in range(df.shape[1]):
            s = _norm(df.iat[i, j])
            if s:
                out[(i, j)] = s
    return out


def _check_summary_header(df, path):
    """総括表の部門の並びが COL の前提どおりか。違えば読まずに止める。"""
    cells = _header_cells(df)
    for side, off in (("資産側", 0), ("負債側", LIAB_OFFSET)):
        for col, label in _SUMMARY_HEADER.items():
            found = [s for (i, j), s in cells.items() if j == col + off]
            if not any(s.startswith(label) for s in found):
                raise ValueError("%s: 総括表の%s %d列目が「%s」ではありません: %s"
                                 % (os.path.basename(path), side, col + off, label, found))


def _cb_columns(df):
    """金融機関の内訳表で「中央銀行」の列を見出しから探す。

    2024年度確報は資産側と負債側が同じシートに左右で並ぶので2列見つかる。
    2023年度確報は資産側と負債側が別ファイルなので1列しか無い。"""
    cells = _header_cells(df)
    cols = sorted(j for (i, j), s in cells.items() if s == CB_LABEL)
    if len(cols) not in (1, 2):
        raise ValueError("「%s」の列が %d 個見つかりました（1か2のはず）" % (CB_LABEL, len(cols)))
    return cols


def net(df, rows, col, liab_offset):
    """純計（資産側 - 負債側）。同じ表の中に負債側があるとき。"""
    return net2(df, rows, col, df, rows, col + liab_offset)


def net2(df_a, rows_a, col_a, df_l, rows_l, col_l):
    """純計（資産側 - 負債側）。資産側と負債側の表を別々に指定する。"""
    a = aggregate(df_a, rows_a, col_a)
    l = aggregate(df_l, rows_l, col_l)
    return dict((k, a[k] - l[k]) for k in a)


def _check_total(df, rows, col, path, what):
    """統合した6種の合計が、原表の「合計」行と一致するか。

    49品目を6種に割り振る aggregate() に漏れが無いことの確認。原表に合計行が
    無い表（取引表）では何もしない。"""
    key = [k for k in rows if k.startswith("9.合計") or k == "合計"]
    if not key:
        return
    tot = _num(df, rows[key[0]], col)
    mine = sum(aggregate(df, rows, col).values())
    if abs(mine - tot) > 0.5:                     # 十億円。原表は小数1桁
        raise ValueError("%s: %s の6種の合計 %.1f が原表の合計 %.1f と合いません"
                         % (os.path.basename(path), what, mine, tot))


def read_year(sum_path, fin_path, sheet, fin_liab_path=None):
    """1年度ぶんを 6部門 × 6資産 + 金融純負債 に組み立てる。

    fin_liab_path は、内訳表の負債側が別ファイルのとき（2023年度確報）に渡す。"""
    ds = pd.read_excel(sum_path, sheet_name=sheet, header=None)
    dfin = pd.read_excel(fin_path, sheet_name=sheet, header=None)
    _check_summary_header(ds, sum_path)
    rs, rf = _rowmap(ds), _rowmap(dfin)

    cb_cols = _cb_columns(dfin)
    if len(cb_cols) == 2:                          # 資産側と負債側が同じシート
        if fin_liab_path is not None:
            raise ValueError("内訳表に負債側があるのに、負債側のファイルも渡されています")
        dfl, rl, col_l = dfin, rf, cb_cols[1]
    else:                                          # 負債側は別ファイル
        if fin_liab_path is None:
            raise ValueError("%s に負債側の「%s」列が無く、負債側のファイルも渡されていません"
                             % (os.path.basename(fin_path), CB_LABEL))
        dfl = pd.read_excel(fin_liab_path, sheet_name=sheet, header=None)
        rl = _rowmap(dfl)
        (col_l,) = _cb_columns(dfl)
    for sec, col in COL.items():
        if sec == "SUM":
            continue
        _check_total(ds, rs, col, sum_path, "%s 資産側" % sec)
        _check_total(ds, rs, col + LIAB_OFFSET, sum_path, "%s 負債側" % sec)
    _check_total(dfin, rf, cb_cols[0], fin_path, "CB 資産側")
    _check_total(dfl, rl, col_l, fin_liab_path or fin_path, "CB 負債側")

    nfc = net(ds, rs, COL["NFC"], LIAB_OFFSET)
    npi = net(ds, rs, COL["NPISH"], LIAB_OFFSET)
    fin = net(ds, rs, COL["FIN"], LIAB_OFFSET)
    cb = net2(dfin, rf, cb_cols[0], dfl, rl, col_l)

    out = {}
    # 非金融法人は、対家計民間非営利団体を統合する（表2）
    out["N"] = dict((k, nfc[k] + npi[k]) for k in TYPES)
    out["CB"] = cb
    # 他金融機関は、金融機関から日本銀行を除いたもの（表2）
    out["F"] = dict((k, fin[k] - cb[k]) for k in TYPES)
    out["G"] = net(ds, rs, COL["G"], LIAB_OFFSET)
    out["H"] = net(ds, rs, COL["H"], LIAB_OFFSET)
    out["W"] = net(ds, rs, COL["W"], LIAB_OFFSET)

    row = {}
    for sec in SECTORS:
        for t in TYPES:
            row["N%sA_%s" % (t, sec)] = out[sec][t]
        # 金融純負債。金融純資産と符号が逆で、資産側に書かれる（表9）
        row["NNFWA_%s" % sec] = -sum(out[sec][t] for t in TYPES)
    return row


def build(kind):
    """kind は 'stock' か 'flow'。"""
    sum_path = fetch(FILES["%s_sum" % kind])
    fin_path = fetch(FILES["%s_fin" % kind])
    sheets = pd.ExcelFile(sum_path).sheet_names
    # 内訳表に負債側の「中央銀行」列が無ければ、負債側は別ファイル
    first = pd.read_excel(fin_path, sheet_name=sheets[-1], header=None)
    liab_path = None
    if len(_cb_columns(first)) == 1:
        liab_path = fetch(FILES["%s_fin_liab" % kind])
        print("   内訳表は資産側と負債側が別ファイル: %s / %s"
              % (os.path.basename(fin_path), os.path.basename(liab_path)))
    rows = {}
    for sh in sheets:
        rows[sheet_year(sh)] = read_year(sum_path, fin_path, sh, liab_path)
    d = pd.DataFrame(rows).T.sort_index()
    d.index.name = "年度"
    return d


def check(d, label):
    """各部門で、6資産の純計と金融純負債の合計がゼロになるか（表9）。

    これは作り方から必ず成り立つので、列を取り違えても通ってしまう（日銀の列の
    取り違えはこれでは捕まらなかった）。
    そこで残高については、日銀の現金・HPM の純計（発行銀行券と日銀当座預金は
    日銀の負債）が、他の5部門の保有の合計を打ち消す大きさの負値であることも
    見る。日銀の負債側を読み損ねると、ここが小さな値になる。"""
    worst = 0.0
    for sec in SECTORS:
        s = sum(d["N%sA_%s" % (t, sec)] for t in TYPES) + d["NNFWA_%s" % sec]
        worst = max(worst, s.abs().max())
    ok = worst < 1e-6
    print("   %-6s 部門ごとの縦計がゼロか: %s (最大のずれ %.3g 十億円)"
          % (label, "OK" if ok else "NG", worst))
    if label == "残高":
        others = sum(d["NGSHA_%s" % s] for s in SECTORS if s != "CB")
        bad = d.index[(d["NGSHA_CB"] >= 0) | (d["NGSHA_CB"].abs() < 0.5 * others.abs())]
        ok_cb = len(bad) == 0
        print("   %-6s 日銀の現金・HPM が他部門の保有を打ち消す負値か: %s%s"
              % (label, "OK" if ok_cb else "NG",
                 "" if ok_cb else "（%s年度）" % ", ".join(str(y) for y in bad[:5])))
        ok = ok and ok_cb
    return ok


def main():
    print("=" * 74)
    print("資金循環データセットの作成（内閣府 国民経済計算 %d年度確報）" % FY)
    print("=" * 74)

    print("\n[1] 残高（ストック）")
    stock = build("stock")
    print("\n[2] 取引（フロー）")
    flow = build("flow")

    print("\n[3] 検算")
    ok_all = []
    ok_all.append(check(stock, "残高"))
    ok_all.append(check(flow, "取引"))

    print("\n[4] 評価調整 = 残高 - 前期残高 - 取引")
    cg = stock - stock.shift(1) - flow
    cg = cg.iloc[1:]                       # 初年度は前期残高が無いので落とす
    cg.columns = [c.replace("A_", "ACG_") if "A_" in c else c for c in cg.columns]

    print("\n[5] 安全資産の保有シェア")
    # 安全資産 NSA は GSH・GB・DEP の合計。論文はこれを固定シェアで3つに割る
    # （例: NGSHA_H = NGSHshare_H * NSA_H）。シェアは実績から作る外生変数。
    share = pd.DataFrame(index=stock.index)
    for sec in ["N", "H", "W"]:
        nsa = sum(stock["N%sA_%s" % (t, sec)] for t in ["GSH", "GB", "DEP"])
        for t in ["GSH", "GB", "DEP"]:
            share["N%sSHARE_%s" % (t, sec)] = stock["N%sA_%s" % (t, sec)] / nsa
        gap = (sum(share["N%sSHARE_%s" % (t, sec)] for t in ["GSH", "GB", "DEP"]) - 1).abs().max()
        print("   %-2s シェア合計が1か: %s (最大のずれ %.3g)"
              % (sec, "OK" if gap < 1e-9 else "NG", gap))
        ok_share = gap < 1e-9
        if not ok_share:
            ok_all.append(False)

    # 十億円の系列は小数4桁で十分だが、シェアは4桁に丸めると合計が 1±0.0001 に
    # ずれ、モデル側で NGSHA+NGBA+NDEPA が NSA と食い違って各部門の横計
    # TOTAL_s が 0.1〜0.8 兆円ずれる（残余で閉じる F と W に鏡像で溜まる）。
    # 上で 1e-9 まで検算した精度をそのまま残す。
    if not all(ok_all):
        # 検算に落ちたときは書かない。前回の正常な CSV を残す（fetch_misc.py と同じ）。
        # 書いてから失敗を返すと、直前の正常な CSV が失われる。
        print("=" * 74)
        print("検算に失敗した。統合ルールを見直すこと。CSV は書き換えていない。")
        return 1
    for name, d, nd in [("japan_ff_stock_fy.csv", stock, 4),
                        ("japan_ff_flow_fy.csv", flow, 4),
                        ("japan_ff_cg_fy.csv", cg, 4),
                        ("japan_ff_share_fy.csv", share, 12)]:
        d.round(nd).to_csv(name, encoding="utf-8-sig")
        print("   %-24s %d年度 × %d系列" % (name, len(d), d.shape[1]))

    print("\n   期間: %d - %d 年度" % (stock.index.min(), stock.index.max()))
    print("=" * 74)
    print("完了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
