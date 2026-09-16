"""fetch_sector.py -- 制度部門別勘定から外生変数26本を作る。

朴(2025c) の外生変数のうち、資本移転・土地純購入・固定資本減耗・各種の
経常移転・営業余剰シェアは、国民経済計算の制度部門別所得支出勘定および
資本勘定から取る（本体 4章）。

論文の変数表はもとの『年報』の項目番号で出典を示しているが、公表されている
Excel では部門によって項目番号がずれる（在庫変動の有無で 1.3 以降が動く）。
そのため項目名で引く。

検算として、各部門で SNA 自身の恒等式

    純貸出 = 貯蓄(総) - 投資 - 土地純購入 + 資本移転(純)

が成り立つことを確認する。これは朴モデルの NL_X の式と同じ形である。

出力: japan_sector_fy.csv
"""
import os
import re
import sys
import time

import numpy as np
import pandas as pd
import requests

from fetch_ff import FY          # 確報の対象年度は fetch_ff が持つ
BASE = ("https://www.esri.cao.go.jp/jp/sna/data/data_list/kakuhou/files/"
        "%d/tables/" % FY)
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")

# 部門記号 -> 制度部門別勘定のファイル
SEC_FILE = {"N1": "%di2_jp.xlsx" % FY,   # 非金融法人企業
            "F":  "%di3_jp.xlsx" % FY,   # 金融機関
            "G":  "%di4_jp.xlsx" % FY,   # 一般政府
            "H":  "%di5_jp.xlsx" % FY,   # 家計
            "N2": "%di6_jp.xlsx" % FY}   # 対家計民間非営利団体
CAP_FILE = {"N1": "%dc1_jp.xlsx" % FY, "F": "%dc2_jp.xlsx" % FY,
            "G":  "%dc3_jp.xlsx" % FY, "H": "%dc4_jp.xlsx" % FY,
            "N2": "%dc5_jp.xlsx" % FY}
ROW_FILE = "%da4_jp.xlsx" % FY          # 海外勘定


def fetch(fname):
    path = os.path.join(CACHE, fname)
    if os.path.exists(path):
        return path
    if not os.path.isdir(CACHE):
        os.makedirs(CACHE)
    for attempt in range(4):
        try:
            r = requests.get(BASE + fname, timeout=90)
            r.raise_for_status()
            with open(path, "wb") as fh:
                fh.write(r.content)
            print("   取得 %s (%.0f KB)" % (fname, len(r.content) / 1024.0))
            time.sleep(1)
            return path
        except Exception as ex:
            if attempt == 3:
                raise
            print("   再試行 %s (%s)" % (fname, str(ex)[:60]))
            time.sleep(2 ** attempt)


def read_sna(fname, sheet):
    """ESRI の制度部門別勘定シートを 年度 x 項目 の DataFrame にする。

    項目名から先頭の項目番号と末尾の参照（(2.4) など）を落として키にする。"""
    df = pd.read_excel(fetch(fname), sheet_name=sheet, header=None)
    yr_row = None
    for i in range(min(12, len(df))):
        nums = [df.iat[i, c] for c in range(1, df.shape[1])]
        nums = [v for v in nums
                if isinstance(v, (int, float)) and not pd.isna(v) and 1900 < v < 2100]
        if len(nums) > 20:
            yr_row = i
            break
    if yr_row is None:
        raise ValueError("年の見出し行が見つかりません: %s %s" % (fname, sheet))
    years = {}
    for c in range(1, df.shape[1]):
        v = df.iat[yr_row, c]
        if isinstance(v, (int, float)) and not pd.isna(v) and 1900 < v < 2100:
            years[int(v)] = c
    out = {}
    for i in range(len(df)):
        v = df.iat[i, 0]
        if pd.isna(v):
            continue
        k = re.sub(r"\s|　", "", str(v))
        k = re.sub(r"^\d+\.\d+", "", k).strip()
        k = re.sub(r"\(.*?\)$", "", k)
        if not k or k in out:
            continue
        row = {}
        for y, c in years.items():
            x = df.iat[i, c]
            row[y] = float(x) if isinstance(x, (int, float)) and not pd.isna(x) else np.nan
        out[k] = row
    return pd.DataFrame(out)


def _key(v):
    """項目名から、先頭の項目番号と末尾の参照（(2.4) など）を落とす。"""
    k = re.sub(r"\s|　", "", str(v))
    k = re.sub(r"^\d+\.\d+", "", k).strip()
    return re.sub(r"\(.*?\)$", "", k)


def _year_cols(df):
    for i in range(min(12, len(df))):
        nums = [df.iat[i, c] for c in range(1, df.shape[1])]
        nums = [v for v in nums
                if isinstance(v, (int, float)) and not pd.isna(v) and 1900 < v < 2100]
        if len(nums) > 20:
            return dict((int(df.iat[i, c]), c) for c in range(1, df.shape[1])
                        if isinstance(df.iat[i, c], (int, float))
                        and not pd.isna(df.iat[i, c]) and 1900 < df.iat[i, c] < 2100)
    raise ValueError("年の見出し行が見つかりません")


def read_sna_sided(fname, sheet):
    """第1次所得の配分勘定を、受取側だけ読む。

    この勘定は「（１）利子」のような同じ項目名が支払側と受取側の両方に
    現れる。read_sna は先に出てきた支払側しか返さないので、受取側を取る
    ときはこちらを使う。シートの途中にある「支払」の小計行を境目にする。"""
    df = pd.read_excel(fetch(fname), sheet_name=sheet, header=None)
    split = None
    for i in range(len(df)):
        if _key(df.iat[i, 0]) == "支払" if not pd.isna(df.iat[i, 0]) else False:
            split = i
            break
    if split is None:
        raise ValueError("支払側と受取側の境目が見つかりません: %s %s" % (fname, sheet))
    years = _year_cols(df)
    out = {}
    for i in range(split + 1, len(df)):
        v = df.iat[i, 0]
        if pd.isna(v):
            continue
        k = _key(v)
        if not k or k in out:
            continue
        out[k] = dict((y, float(df.iat[i, c])
                       if isinstance(df.iat[i, c], (int, float)) and not pd.isna(df.iat[i, c])
                       else np.nan) for y, c in years.items())
    return pd.DataFrame(out)


def pick(d, *names):
    """候補名のうち最初に見つかった列を返す。部門で表記が揺れるため。"""
    for n in names:
        if n in d.columns:
            return d[n]
    raise KeyError("項目が見つかりません: %s / 候補=%s" % (names, list(d.columns)[:14]))


def main():
    print("=" * 74)
    print("制度部門別勘定からの外生変数（内閣府 国民経済計算 %d年度確報）" % FY)
    print("=" * 74)

    out = pd.DataFrame()
    fail = []

    print("\n[1] 資本勘定")
    cap = {}
    for sec, f in CAP_FILE.items():
        cap[sec] = read_sna(f, "年度（１）資本")

    for sec in CAP_FILE:
        d = cap[sec]
        recv = pick(d, "資本移転（受取）", "資本移転等（受取）")
        pay = pick(d, "（控除）資本移転（支払）", "（控除）資本移転等（支払）")
        ktr = recv - pay
        dep = pick(d, "（控除）固定資本減耗")
        land = pick(d, "土地の購入（純）")
        ifix = pick(d, "総固定資本形成")
        inv = d["在庫変動"] if "在庫変動" in d.columns else 0.0
        # SNA の純貸出。総貯蓄 = 貯蓄(純) + 固定資本減耗、投資 = 総固定資本形成 + 在庫変動
        s_gross = pick(d, "貯蓄（純）") + dep
        nl_calc = s_gross - (ifix + inv) - land + ktr
        nl_book = pick(d, "純貸出")
        gap = (nl_calc - nl_book).abs().max()
        # 原表は 0.1 十億円（1億円）刻みで丸められている。5項目を足し引きするので
        # 丸めだけで 0.25 程度は動く。それを超えたら抽出の誤りとみなす。
        ok = gap < 0.5
        print("   %-3s 純貸出の恒等式: %-2s (最大のずれ %.4g 十億円)"
              % (sec, "OK" if ok else "NG", gap))
        if not ok:
            fail.append("純貸出恒等式 %s" % sec)
        cap[sec] = dict(KTR=ktr, D=dep, NP=land, I=ifix + inv)

    # 非金融法人(N)は対家計民間非営利団体を統合する（本体 表2）
    out["KTR_N"] = cap["N1"]["KTR"] + cap["N2"]["KTR"]
    out["NP_N"] = cap["N1"]["NP"] + cap["N2"]["NP"]
    for sec in ["F", "G", "H"]:
        out["KTR_%s" % sec] = cap[sec]["KTR"]
        out["NP_%s" % sec] = cap[sec]["NP"]
    out["D_F"] = cap["F"]["D"]
    out["D_G"] = cap["G"]["D"]

    print("\n[2] 海外勘定")
    row_cur = read_sna(ROW_FILE, "年度（１）経常")
    row_cap = read_sna(ROW_FILE, "年度（２）資本")
    out["KTR_W"] = pick(row_cap, "資本移転等（受取）") - pick(row_cap, "（控除）資本移転等（支払）")
    out["STR_W"] = (pick(row_cur, "その他の経常移転（受取）")
                    - pick(row_cur, "その他の経常移転（支払）"))
    out["T_W"] = 0.0            # 海外勘定に税の項目は立っていない（変数表も出典欄が空）
    print("   KTR_W / STR_W を取得。T_W は海外勘定に項目が無いのでゼロとする")

    print("\n[3] 所得支出勘定")
    inc2 = dict((s, read_sna(f, "年度（２）")) for s, f in SEC_FILE.items())

    def tax_of(d):
        """直接税（支払）。立っていない部門（対家計民間非営利団体）はゼロ。"""
        n = "所得・富等に課される経常税（支払）"
        return d[n] if n in d.columns else 0.0

    def str_of(d):
        """移転純受取。

        第2次分配勘定は 可処分所得(純) = 第1次所得バランス(純) + Σ受取 - Σ支払
        という恒等式になっている。移転の項目名は部門ごとに違う（対家計民間
        非営利団体には「その他の経常移転（支払）」が無く、代わりに
        「非生命純保険料（支払）」が立つ）ので、項目を数え上げるのではなく
        この恒等式から出す。税は別に扱うので足し戻す。"""
        return (pick(d, "可処分所得（純）") - pick(d, "第１次所得バランス（純）")
                + tax_of(d))

    out["STR_F"] = str_of(inc2["F"])
    out["STR_N"] = str_of(inc2["N1"]) + str_of(inc2["N2"])
    out["T_F"] = tax_of(inc2["F"])

    inc3_f = read_sna(SEC_FILE["F"], "年度（３）")
    out["CPEN_F"] = pick(inc3_f, "年金受給権の変動調整（支払）")
    inc4_h = read_sna(SEC_FILE["H"], "年度（４）a")
    out["CPEN_H"] = pick(inc4_h, "年金受給権の変動調整（受取）")

    inc3_h = read_sna(SEC_FILE["H"], "年度（３）")
    out["OTR_H"] = (pick(inc2["H"], "その他の経常移転（受取）")
                    + pick(inc3_h, "現物社会移転（受取）")
                    - pick(inc2["H"], "その他の経常移転（支払）"))

    print("\n[4] 営業余剰のシェア")
    # 営業余剰は固定資本減耗を含む総概念（本体 4.1）
    inc1 = dict((s, read_sna(f, "年度（１）")) for s, f in SEC_FILE.items())

    def b2_gross(sec):
        """営業余剰（総）。一般政府と対家計民間非営利団体は非市場生産者なので
        第1次所得の配分勘定に営業余剰の項目が立たない（純額はゼロ）。
        総概念にするため、いずれの部門も固定資本減耗を足す。"""
        d = inc1[sec]
        net = 0.0
        for n in ("営業余剰（純）", "営業余剰・混合所得（純）"):
            if n in d.columns:
                net = d[n]
                break
        return net + cap[sec]["D"]

    b2 = dict((sec, b2_gross(sec)) for sec in SEC_FILE)
    # 家計は「（再掲）営業余剰・混合所得（総）」が直接載っているので突き合わせる
    hh = inc1["H"]
    if "（再掲）営業余剰・混合所得（総）" in hh.columns:
        g = (b2["H"] - hh["（再掲）営業余剰・混合所得（総）"]).abs().max()
        print("   家計の営業余剰（総）が原表と一致するか: %s (最大のずれ %.3g 十億円)"
              % ("OK" if g < 0.5 else "NG", g))
        if g >= 0.5:
            fail.append("家計の営業余剰")
    b2_n = b2["N1"] + b2["N2"]
    b2_sum = b2_n + b2["F"] + b2["G"] + b2["H"]
    out["SB2_N"] = b2_n / b2_sum
    for sec in ["F", "G", "H"]:
        out["SB2_%s" % sec] = b2[sec] / b2_sum
    share_sum = out[["SB2_N", "SB2_F", "SB2_G", "SB2_H"]].sum(axis=1)
    gap = (share_sum - 1).abs().max()
    print("   シェア合計が1か: %s (最大のずれ %.3g)" % ("OK" if gap < 1e-9 else "NG", gap))
    if gap >= 1e-9:
        fail.append("営業余剰シェア")

    print("\n[5] 実質の政府消費と投資")
    # 主要系列表1（国内総生産・支出側）。政府消費は「政府現実最終消費」を使う（本体 4.4）
    real = read_sna("%dffm1rn_jp.xlsx" % FY, "実数")
    defl = read_sna("%dffm1dn_jp.xlsx" % FY, "実数")
    out["GR"] = real["政府現実最終消費"]
    # 投資デフレータは総資本形成のもの。指数(2020=100)を1基準に直す（本体 4.1）
    # 主要系列表の項目名は全角の番号つき（'３．総資本形成'）
    pi = pick(defl, "３．総資本形成", "総資本形成") / 100.0
    out["IR_F"] = cap["F"]["I"] / pi
    out["IR_G"] = cap["G"]["I"] / pi
    print("   政府現実最終消費（実質）と、総資本形成デフレータで実質化した投資を取得")
    print("   最終年度: GR=%.1f  IR_F=%.1f  IR_G=%.1f (十億円)"
          % (out["GR"].loc[FY], out["IR_F"].loc[FY], out["IR_G"].loc[FY]))

    out = out.sort_index()
    out.index.name = "年度"
    print("=" * 74)
    if fail:
        # 検算に落ちたときは書かない。前回の正常な CSV を残す（fetch_misc.py と同じ）
        print("検算に失敗:", ", ".join(fail))
        print("   japan_sector_fy.csv は書き換えていない")
        return 1
    out.round(4).to_csv("japan_sector_fy.csv", encoding="utf-8-sig")
    print("   japan_sector_fy.csv  %d年度 × %d系列 (%d-%d)"
          % (len(out), out.shape[1], out.index.min(), out.index.max()))
    print("完了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
