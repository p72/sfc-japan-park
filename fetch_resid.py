"""fetch_resid.py -- 他の実データからの残差として決まる外生変数を作る。

朴(2025c) のモデルには、会計の恒等式を実績に合わせるための調整項がいくつも
置かれている。論文はこれらを「データセット作成時に計算する」としている
（本体 4章）。ここでも同じ定義式で作る。

  GAPNL_X   金融勘定の純貸出と、資本勘定から計算した純貸出との差
  KCG_X     名目資本ストックの調整項（キャピタルゲイン）
  STR_GAP   政府の社会移転を他部門の合計から求めるときの開差
  YR_GAP    実質GDPを需要項目の合計から求めるときの開差

EPSILON_X（各部門の貯蓄の開差）と GAPNL_CB は、金利・配当率から計算する
FINCOME_X を必要とするため、ここでは扱わない。

出力: japan_resid_fy.csv
"""
import os
import sys

import pandas as pd

import fetch_sector as fs

HERE = os.path.dirname(os.path.abspath(__file__))
FY = fs.FY

# 期末貸借対照表勘定のファイル。非金融法人(N)は対家計民間非営利団体を含める
BS_FILE = {"N1": "%dsi11_jp.xlsx" % FY, "N2": "%dsi5_jp.xlsx" % FY,
           "F": "%dsi21_jp.xlsx" % FY, "G": "%dsi3_jp.xlsx" % FY,
           "H": "%dsi4_jp.xlsx" % FY}


def main():
    print("=" * 74)
    print("残差として決まる外生変数（内閣府 国民経済計算 %d年度確報）" % FY)
    print("=" * 74)
    out = pd.DataFrame()
    fail = []

    print("\n[1] 純貸出のギャップ GAPNL")
    # 資本勘定の純貸出と、金融勘定の純貸出（資金過不足）は一致しない。
    # 論文はその差を GAPNL として外生で埋める（本体 4.1）。
    cap, fin = {}, {}
    for sec, f in fs.CAP_FILE.items():
        c = fs.read_sna(f, "年度（１）資本")
        cap[sec] = fs.pick(c, "純貸出")
        g = fs.read_sna(f, "年度（２）金融")
        fin[sec] = fs.pick(g, "純貸出(+)／純借入(-)（資金過不足）", "純貸出")
    out["GAPNL_N"] = (fin["N1"] - cap["N1"]) + (fin["N2"] - cap["N2"])
    for sec in ["F", "G", "H"]:
        out["GAPNL_%s" % sec] = fin[sec] - cap[sec]
    for sec in ["N", "F", "G", "H"]:
        print("   GAPNL_%-2s 最終年度 %10.1f 十億円" % (sec, out["GAPNL_%s" % sec].iloc[-1]))

    # 海外は 資本勘定を持たないので S_W + KTR_W と金融勘定の差をとる
    row_cur = fs.read_sna("%da4_jp.xlsx" % FY, "年度（１）経常")
    row_cap = fs.read_sna("%da4_jp.xlsx" % FY, "年度（２）資本")
    row_fin = fs.read_sna("%da4_jp.xlsx" % FY, "年度（３）金融")
    s_w = fs.pick(row_cur, "経常対外収支")
    ktr_w = (fs.pick(row_cap, "資本移転等（受取）")
             - fs.pick(row_cap, "（控除）資本移転等（支払）"))
    nl_w = fs.pick(row_fin, "純貸出(+)／純借入(-)（資金過不足）", "純貸出")
    out["GAPNL_W"] = nl_w - (s_w + ktr_w)
    print("   GAPNL_W  最終年度 %10.1f 十億円" % out["GAPNL_W"].iloc[-1])

    print("\n[2] 資本ストックの調整項 KCG")
    # Kn_X = Kn_X(-1) + In_X - D_X + KCG_X を満たすように置く（本体 4.1）
    bs = dict((s, fs.read_sna(f, "期末貸借対照表")) for s, f in BS_FILE.items())
    kn = {}
    kn["N"] = fs.pick(bs["N1"], "ａ．固定資産") + fs.pick(bs["N2"], "ａ．固定資産")
    for sec in ["F", "G", "H"]:
        kn[sec] = fs.pick(bs[sec], "ａ．固定資産")

    cap_items = {}
    for sec, f in fs.CAP_FILE.items():
        d = fs.read_sna(f, "年度（１）資本")
        inv = d["在庫変動"] if "在庫変動" in d.columns else 0.0
        cap_items[sec] = dict(I=fs.pick(d, "総固定資本形成") + inv,
                              D=fs.pick(d, "（控除）固定資本減耗"))
    inv_n = cap_items["N1"]["I"] + cap_items["N2"]["I"]
    dep_n = cap_items["N1"]["D"] + cap_items["N2"]["D"]
    out["KCG_N"] = kn["N"] - (kn["N"].shift(1) + inv_n - dep_n)
    for sec in ["F", "G", "H"]:
        out["KCG_%s" % sec] = kn[sec] - (kn[sec].shift(1)
                                         + cap_items[sec]["I"] - cap_items[sec]["D"])
    for sec in ["N", "F", "G", "H"]:
        print("   KCG_%-2s 最終年度 %10.1f 十億円" % (sec, out["KCG_%s" % sec].iloc[-1]))

    print("\n[3] 社会移転の開差 STR_GAP")
    # STR_G = -(STR_N + STR_H + STR_F + STR_W) + STR_GAP （本体 4.4）
    inc2 = dict((s, fs.read_sna(f, "年度（２）")) for s, f in fs.SEC_FILE.items())

    def tax_of(d):
        n = "所得・富等に課される経常税（支払）"
        return d[n] if n in d.columns else 0.0

    def str_of(d):
        return (fs.pick(d, "可処分所得（純）") - fs.pick(d, "第１次所得バランス（純）")
                + tax_of(d))

    str_n = str_of(inc2["N1"]) + str_of(inc2["N2"])
    str_f = str_of(inc2["F"])
    # 家計だけはモデルが STR_H = SBEN_H + OTR_H - SCON_H と分解しているので
    # （本体 4.5）、同じ組み立てで作る。恒等式から出すと現物社会移転のぶんずれる。
    inc3_h = fs.read_sna(fs.SEC_FILE["H"], "年度（３）")
    sben_h = fs.pick(inc2["H"], "現物社会移転以外の社会給付（受取）")
    scon_h = fs.pick(inc2["H"], "純社会負担（支払）")
    otr_h = (fs.pick(inc2["H"], "その他の経常移転（受取）")
             + fs.pick(inc3_h, "現物社会移転（受取）")
             - fs.pick(inc2["H"], "その他の経常移転（支払）"))
    str_h = sben_h + otr_h - scon_h
    # 政府は税を受取側に持つので、恒等式から税（受取）を引いて移転だけを残す
    # 政府の移転純受取。Gn に政府「現実」最終消費を使う以上、こちらも
    # 調整可処分所得に合わせる（fetch_endo・fetch_fincome と同じ）。
    g2 = inc2["G"]
    g3 = fs.read_sna(fs.SEC_FILE["G"], "年度（３）")
    str_g = (fs.pick(g3, "調整可処分所得（純）")
             - fs.pick(g2, "第１次所得バランス（純）")
             - fs.pick(g2, "所得・富等に課される経常税（受取）"))
    str_w = (fs.pick(row_cur, "その他の経常移転（受取）")
             - fs.pick(row_cur, "その他の経常移転（支払）"))
    out["STR_GAP"] = str_g + (str_n + str_h + str_f + str_w)
    print("   STR_GAP 最終年度 %10.1f 十億円" % out["STR_GAP"].iloc[-1])

    print("\n[4] 実質GDPの開差 YR_GAP")
    # Yr = Cr + In_H/Ph + In_N/Pi + In_F/Pi + In_G/Pi + Gn/Pg + Xr - Mr + Yr_GAP
    nom = fs.read_sna("%dffm1n_jp.xlsx" % FY, "実数")
    real = fs.read_sna("%dffm1rn_jp.xlsx" % FY, "実数")
    defl = fs.read_sna("%dffm1dn_jp.xlsx" % FY, "実数")
    pi = fs.pick(defl, "３．総資本形成", "総資本形成") / 100.0
    ph = fs.pick(defl, "（ａ）住宅") / 100.0
    pg = fs.pick(defl, "政府現実最終消費") / 100.0
    yr = fs.pick(real, "５．国内総生産（支出側）")
    cr = fs.pick(real, "家計現実最終消費")
    xr = fs.pick(real, "（１）財貨・サービスの輸出")
    mr = fs.pick(real, "（２）（控除）財貨・サービスの輸入")
    gn = fs.pick(nom, "政府現実最終消費")
    in_h = cap_items["H"]["I"]
    in_n = inv_n
    in_f = cap_items["F"]["I"]
    in_g = cap_items["G"]["I"]
    out["YR_GAP"] = yr - (cr + in_h / ph + (in_n + in_f + in_g) / pi
                          + gn / pg + xr - mr)
    rel = (out["YR_GAP"] / yr * 100).abs()
    print("   YR_GAP 最終年度 %10.1f 十億円（実質GDP比 %.2f%%）"
          % (out["YR_GAP"].iloc[-1], rel.iloc[-1]))
    print("   開差の実質GDP比: 平均 %.2f%% / 最大 %.2f%%" % (rel.mean(), rel.max()))
    if rel.max() > 5.0:
        # 連鎖方式なので開差は残るが、数％を超えるなら項目の取り違えを疑う
        fail.append("YR_GAP が大きすぎる")
    # YR_GAP の正体は連鎖方式の非加法性なので、連鎖の参照年ではほぼゼロになり、
    # 公表されている「６．開差」とよく似た動きをするはずである。
    # 参照年は確報の版で変わる（2023年度確報は2015年、2024年度確報は2020年）ので、
    # 実質GDP＝名目GDP になる年をデータから拾う。ここを直書きすると、版を
    # 変えたときに黙って落ちる（実際 2024→2023 で落ちた）。
    ref = int((yr - fs.pick(nom, "５．国内総生産（支出側）")).abs().idxmin())
    kaisa = fs.pick(real, "６．開差")
    corr = out["YR_GAP"].corr(kaisa)
    print("   連鎖の参照年 %d での開差 %.3f%%（実質GDP比）"
          "／公表『６．開差』との相関 %.3f" % (ref, rel.loc[ref], corr))
    if rel.loc[ref] > 0.05 or corr < 0.9:
        fail.append("YR_GAP が連鎖の開差として説明できない")

    print("\n[5] 検算")
    miss = [c for c in out.columns if out[c].iloc[1:].isna().any()]
    print("   初年度を除く欠測: %s" % ("なし" if not miss else miss))
    if miss:
        fail.append("欠測")

    out = out.sort_index()
    out.index.name = "年度"
    print("=" * 74)
    if fail:
        # 検算に落ちたときは書かない。前回の正常な CSV を残す（fetch_misc.py と同じ）
        print("検算に失敗:", ", ".join(fail))
        print("   japan_resid_fy.csv は書き換えていない")
        return 1
    out.round(4).to_csv("japan_resid_fy.csv", encoding="utf-8-sig")
    print("   japan_resid_fy.csv  %d年度 × %d系列 (%d-%d)"
          % (len(out), out.shape[1], out.index.min(), out.index.max()))
    print("完了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
