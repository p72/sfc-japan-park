"""fetch_endo.py -- 内生変数の実績値を用意する。

パーシャルテスト（各内生変数の式に、当期の外生変数と先決内生変数の実績を
入れるだけの計算）と、ファイナルテストの誤差率を出すには、内生変数の実績が
要る。ラグ参照される70本のうち35本は他のファイルで作った資金循環データに
含まれるので、ここでは残りを国民経済計算から組み立てる。

出力: japan_endo_fy.csv
"""
import os
import sys

import numpy as np
import pandas as pd

import fetch_ff as ff
import fetch_sector as fs

FY = fs.FY
TYPES = ["GSH", "GB", "DEP", "LBD", "EQU", "PEN"]


def production_function(yr, kn_g, py, w_hours, n_n, load, kn_n, y0=1994, y1=None):
    """生産関数 LOG(YR) = c + a*LOG(KN_G/PY) + b*LOG(W_HOURS*N_N) + g*LOG(LOAD*KN_N/PY)
    を y0-y1 年度の OLS で推定する（本体 4.6）。

    返り値は (c, a, b, g, loadmax)。loadmax は y0-y1 の稼働率指数の最大値で、
    潜在GDPを計算するときに LOAD の代わりに入れる（論文の LOADmax = 135.6667
    に相当）。reestimate.py も同じ関数で係数を作るので、実績の GDPGAP と
    モデルの gdpmax が同じ生産関数になる。"""
    y1 = int(yr.index.max()) if y1 is None else y1
    years = [y for y in range(y0, y1 + 1)
             if all(pd.notna(x.get(y)) for x in (yr, kn_g, py, w_hours, n_n, load, kn_n))]
    if len(years) < 20:
        raise ValueError("生産関数の推定に使える年度が %d しかありません" % len(years))
    X = np.column_stack([np.ones(len(years)),
                         [np.log(kn_g[y] / py[y]) for y in years],
                         [np.log(w_hours[y] * n_n[y]) for y in years],
                         [np.log(load[y] * kn_n[y] / py[y]) for y in years]])
    Y = np.array([np.log(yr[y]) for y in years])
    c0, a, b, g = np.linalg.lstsq(X, Y, rcond=None)[0]
    loadmax = float(max(load[y] for y in years))
    return float(c0), float(a), float(b), float(g), loadmax


def main():
    print("=" * 74)
    print("内生変数の実績値（国民経済計算 %d年度確報）" % FY)
    print("=" * 74)
    fail = []
    o = pd.DataFrame()

    print("\n[1] GDPと需要項目、デフレータ")
    nom = fs.read_sna("%dffm1n_jp.xlsx" % FY, "実数")
    real = fs.read_sna("%dffm1rn_jp.xlsx" % FY, "実数")
    defl = fs.read_sna("%dffm1dn_jp.xlsx" % FY, "実数")
    o["YN"] = fs.pick(nom, "５．国内総生産（支出側）")
    o["YR"] = fs.pick(real, "５．国内総生産（支出側）")
    o["CR"] = fs.pick(real, "家計現実最終消費")
    o["XR"] = fs.pick(real, "（１）財貨・サービスの輸出")
    o["MR"] = fs.pick(real, "（２）（控除）財貨・サービスの輸入")
    # デフレータは指数(2020=100)を1基準に直す（本体 4.1）
    for name, key in [("PY", "５．国内総生産（支出側）"), ("PC", "家計現実最終消費"),
                      ("PG", "政府現実最終消費"), ("PI", "３．総資本形成"),
                      ("PH", "（ａ）住宅"), ("PX", "（１）財貨・サービスの輸出"),
                      ("PM", "（２）（控除）財貨・サービスの輸入")]:
        o[name] = fs.pick(defl, key) / 100.0
    print("   YN / YR / CR / XR / MR と デフレータ7本")

    print("\n[2] 資本ストックと実質投資")
    bs = {"N1": "%dsi11_jp.xlsx" % FY, "N2": "%dsi5_jp.xlsx" % FY,
          "F": "%dsi21_jp.xlsx" % FY, "G": "%dsi3_jp.xlsx" % FY, "H": "%dsi4_jp.xlsx" % FY}
    kn = dict((s, fs.pick(fs.read_sna(f, "期末貸借対照表"), "ａ．固定資産"))
              for s, f in bs.items())
    o["KN_N"] = kn["N1"] + kn["N2"]
    for s in ["F", "G", "H"]:
        o["KN_%s" % s] = kn[s]
    cap = {}
    for sec, f in fs.CAP_FILE.items():
        d = fs.read_sna(f, "年度（１）資本")
        inv = d["在庫変動"] if "在庫変動" in d.columns else 0.0
        cap[sec] = fs.pick(d, "総固定資本形成") + inv
    o["IR_N"] = (cap["N1"] + cap["N2"]) / o["PI"]
    o["IR_H"] = cap["H"] / o["PH"]
    print("   KN_N/F/G/H と IR_N / IR_H")

    print("\n[3] 労働と賃金")
    misc = pd.read_csv("japan_misc_fy.csv", index_col=0, encoding="utf-8-sig")
    a1 = fs.read_sna("%da1_jp.xlsx" % FY, "年度")
    # 就業者数は労働力人口から完全失業者を引いたもの（fetch_misc と同じ作り）
    lab, _ = __import__("fetch_misc").fetch_labour()
    o["N_N"] = lab["EMP"]
    o["UN"] = lab["UN"]
    o["W"] = a1["雇用者報酬"] / o["N_N"]
    print("   N_N / UN / W（最終年度の賃金率 %.1f 十億円/万人）" % o["W"].iloc[-1])

    print("\n[4] 税と所得")
    inc2 = dict((s, fs.read_sna(f, "年度（２）")) for s, f in fs.SEC_FILE.items())
    inc1 = dict((s, fs.read_sna(f, "年度（１）")) for s, f in fs.SEC_FILE.items())
    capd = {}
    for sec, f in fs.CAP_FILE.items():
        capd[sec] = fs.pick(fs.read_sna(f, "年度（１）資本"), "（控除）固定資本減耗")
    o["TIN_N"] = a1["生産・輸入品に課される税"] - a1["（控除）補助金"]
    o["TD_N"] = fs.pick(inc2["N1"], "所得・富等に課される経常税（支払）")
    o["T_H"] = fs.pick(inc2["H"], "所得・富等に課される経常税（支払）")

    def b2_gross(sec):
        d = inc1[sec]
        net = 0.0
        for n in ("営業余剰（純）", "営業余剰・混合所得（純）"):
            if n in d.columns:
                net = d[n]
                break
        return net + capd[sec]
    o["B2_N"] = b2_gross("N1") + b2_gross("N2")

    h2, h3 = inc2["H"], fs.read_sna(fs.SEC_FILE["H"], "年度（３）")
    o["Y_H"] = (fs.pick(h3, "調整可処分所得（純）") + capd["H"]
                + fs.pick(h2, "所得・富等に課される経常税（支払）"))
    # モデルは YD_H = Y_H - T_H で、Y_H は調整可処分所得ベース（本体 4.5）。
    # 可処分所得を使うと現物社会移転のぶんずれる。
    yd_h = o["Y_H"] - o["T_H"]
    o["YDR_H"] = yd_h / o["PC"]
    print("   TIN_N / TD_N / T_H / B2_N / Y_H / YDR_H")

    print("\n[5] 金融のストックから決まるもの")
    st = pd.read_csv("japan_ff_stock_fy.csv", index_col=0, encoding="utf-8-sig")
    for sec in ["N", "H", "W"]:
        o["NSA_%s" % sec] = sum(st["N%sA_%s" % (t, sec)] for t in ["GSH", "GB", "DEP"])
    o["ASSET_N"] = o["NSA_N"] + st["NNFWA_N"]
    o["LIAB_F"] = -st["NDEPA_F"] - st["NPENA_F"] - st["NNFWA_F"]
    o["LIAB_H"] = -(st["NLBDA_H"] + st["NNFWA_H"])
    # 家計の実質純資産。金融純資産に住宅ストックを足して消費デフレータで割る（本体 4.5）
    o["NWR_H"] = (-st["NNFWA_H"] + o["KN_H"]) / o["PC"]
    print("   NSA_N/H/W / ASSET_N / LIAB_F / LIAB_H / NWR_H")

    print("\n[6] 実質金利と住宅ストック価格")
    fin = pd.read_csv("japan_fincome_fy.csv", index_col=0, encoding="utf-8-sig")
    infl = (o["PC"] - o["PC"].shift(1)) / o["PC"].shift(1)
    o["RRB"] = fin["RB"] - infl
    o["RRL"] = fin["RL"] - infl
    # Phs = Phs(-1) + KCG_H/Kn_H(-1)。初期値は1とする（本体 4.5）
    resid = pd.read_csv("japan_resid_fy.csv", index_col=0, encoding="utf-8-sig")
    phs = pd.Series(index=o.index, dtype=float)
    phs.iloc[0] = 1.0
    for i in range(1, len(o.index)):
        y, yp = o.index[i], o.index[i - 1]
        phs.loc[y] = phs.loc[yp] + resid["KCG_H"].loc[y] / o["KN_H"].loc[yp]
    o["PHS"] = phs
    print("   RRB / RRL / PHS（最終年度 %.3f）" % o["PHS"].iloc[-1])

    print("\n[7] 恒等式で決まるもの")
    # 名目の需要項目と部門別のフロー。ほとんどが定義式なので実績から直接作れる。
    o["CN"] = fs.pick(nom, "家計現実最終消費")
    o["GN"] = fs.pick(nom, "政府現実最終消費")
    o["XN"] = fs.pick(nom, "（１）財貨・サービスの輸出")
    o["MN"] = fs.pick(nom, "（２）（控除）財貨・サービスの輸入")
    o["IN_N"] = cap["N1"] + cap["N2"]
    for s, nm in [("F", "IN_F"), ("G", "IN_G"), ("H", "IN_H")]:
        o[nm] = cap[s]
    o["IN_SUM"] = o["IN_N"] + o["IN_F"] + o["IN_G"] + o["IN_H"]
    o["IR_SUM"] = o["IN_SUM"] / o["PI"]
    o["TB"] = o["XN"] - o["MN"]
    o["TBR"] = o["XR"] - o["MR"]

    o["B2"] = a1["営業余剰・混合所得"] + a1["固定資本減耗"]
    o["B2_F"], o["B2_G"], o["B2_H"] = b2_gross("F"), b2_gross("G"), b2_gross("H")
    o["WB_N"] = a1["雇用者報酬"]
    o["WB_H"] = fs.pick(fs.read_sna_sided(fs.SEC_FILE["H"], "年度（１）"), "雇用者報酬（受取）")
    o["WB_W"] = o["WB_N"] - o["WB_H"]
    o["YFN"] = o["WB_N"] + o["B2"]
    o["WS"] = o["WB_N"] / o["YFN"]
    o["ULC"] = o["WB_N"] / o["YR"]
    o["D_N"] = capd["N1"] + capd["N2"]
    o["D_H"] = capd["H"]

    # 論文の UNR は比率ではなく百分率（UNR = UN/LF*100、変数表も「％」）。
    # 賃金式に 2.414*1/UNR の形で入るので、単位を取り違えると賃金が壊れる。
    o["UNR"] = o["UN"] / (o["UN"] + o["N_N"]) * 100
    o["N_H"] = o["N_N"] - misc["N_W"]
    o["KR_N"] = o["KN_N"] / o["PI"]
    o["KR_H"] = o["KN_H"] / o["PHS"]

    # 貯蓄と純貸出。純貸出は金融勘定の資金過不足を使う（本体 4.1）
    s_gross, nl = {}, {}
    for sec, f in fs.CAP_FILE.items():
        dcap = fs.read_sna(f, "年度（１）資本")
        s_gross[sec] = fs.pick(dcap, "貯蓄（純）") + capd[sec]
        dfin = fs.read_sna(f, "年度（２）金融")
        nl[sec] = fs.pick(dfin, "純貸出(+)／純借入(-)（資金過不足）", "純貸出")
    o["S_N"] = s_gross["N1"] + s_gross["N2"]
    o["NL_N"] = nl["N1"] + nl["N2"]
    for s in ["F", "G", "H"]:
        o["S_%s" % s] = s_gross[s]
        o["NL_%s" % s] = nl[s]
    row_cur = fs.read_sna("%da4_jp.xlsx" % FY, "年度（１）経常")
    row_fin = fs.read_sna("%da4_jp.xlsx" % FY, "年度（３）金融")
    o["S_W"] = fs.pick(row_cur, "経常対外収支")
    o["NL_W"] = fs.pick(row_fin, "純貸出(+)／純借入(-)（資金過不足）", "純貸出")
    cg = pd.read_csv("japan_ff_cg_fy.csv", index_col=0, encoding="utf-8-sig")
    cg_cb = sum(cg["N%sACG_CB" % t] for t in TYPES)
    o["NL_CB"] = st["NNFWA_CB"].shift(1) - cg_cb - st["NNFWA_CB"]

    # 税と移転
    o["T_G"] = fs.pick(inc2["G"], "所得・富等に課される経常税（受取）") + o["TIN_N"]
    o["SBEN_H"] = fs.pick(h2, "現物社会移転以外の社会給付（受取）")
    o["SCON_H"] = fs.pick(h2, "純社会負担（支払）")
    sec_csv = pd.read_csv("japan_sector_fy.csv", index_col=0, encoding="utf-8-sig")
    o["STR_H"] = o["SBEN_H"] + sec_csv["OTR_H"] - o["SCON_H"]
    g2, g3 = inc2["G"], fs.read_sna(fs.SEC_FILE["G"], "年度（３）")
    o["STR_G"] = (fs.pick(g3, "調整可処分所得（純）")
                  - fs.pick(g2, "第１次所得バランス（純）")
                  - fs.pick(g2, "所得・富等に課される経常税（受取）"))
    o["YD_H"] = yd_h

    # 金融の純資産と純資産、部門合計
    for sec in ["N", "CB", "F", "G", "H", "W"]:
        o["FNWL_%s" % sec] = -st["NNFWA_%s" % sec]
        o["FNWLR_%s" % sec] = o["FNWL_%s" % sec] / o["PC"]
        o["TOTAL_%s" % sec] = 0.0        # 縦計はゼロ（本体 表9）
    for sec, k in [("N", "KN_N"), ("F", "KN_F"), ("G", "KN_G"), ("H", "KN_H")]:
        o["NW_%s" % sec] = o["FNWL_%s" % sec] + o[k]
        o["NWR_%s" % sec] = o["NW_%s" % sec] / o["PC"]
    o["TOTAL_SUM"] = 0.0
    for t in TYPES:
        o["N%sA_SUM" % t] = sum(st["N%sA_%s" % (t, s)]
                                for s in ["N", "CB", "F", "G", "H", "W"])
    o["NNFWA_SUM"] = sum(st["NNFWA_%s" % s] for s in ["N", "CB", "F", "G", "H", "W"])
    # 日本の対外純資産。モデルは FA = -FNWL_W で、FNWL_W = -NNFWA_W なので
    # FA = NNFWA_W（海外部門の金融純負債＝日本の純債権）になる。
    o["FA"] = st["NNFWA_W"]
    o["FAB"] = -o["NL_W"]
    o["MB"] = -st["NGSHA_CB"] - st["NGSHA_G"]
    # マネーストックの定義は 朴(2026a) 5節に従う。通貨保有主体は法人・家計に
    # 地方自治体等を加えたもので、海外部門は含まない。政府が日銀に置く預金
    # （NGSHA_G）は中央政府の政府預金とみなして除き、政府が民間銀行に置く預金
    # （NDEPA_G）は地方自治体等の預金とみなして含める。
    # 巻末付録の古い式は海外部門（NGSHA_W, NDEPA_W）を含んでいた。
    o["MS"] = (st["NGSHA_N"] + st["NGSHA_H"]
               + st["NDEPA_N"] + st["NDEPA_G"] + st["NDEPA_H"])
    # 統計上の不突合（SD）。国民経済計算の生産側と分配側の差で、
    #   YFn = Yn - TIN_N - SD,  B2 = YFn - WB_N
    # という関係にある。朴(2026) WP65 は営業余剰 B2 を回帰式からこの残余式に
    # 変えたので、その右辺に要る。作成済みの系列から逆算して置く。
    o["SD"] = o["YN"] - o["WB_N"] - o["TIN_N"] - o["B2"]

    # 実質金利
    o["RRH"] = -infl
    o["RRM"] = fin["RM"] - infl
    o["RCHI"] = fin["CHI"] - infl
    o["RPSI"] = fin["PSI"] - infl
    o["FINCOME_SUM"] = sum(fin["FINCOME_%s" % s]
                           for s in ["N", "CB", "F", "G", "H", "W"])

    # 潜在GDPとGDPギャップ（本体 4.6）。生産関数を実績の労働時間 W_HOURS と
    # 稼働率 LOAD で推定し、その係数に WHMAX と LOAD の最大値を入れる。
    # 論文の係数を直書きすると、
    # モデル側（reestimate.py が推定した係数）と「実績」の GDPGAP がずれ、
    # 賃金式が実績の GDPGAP で推定されているぶん食い違いが出る。
    pf = production_function(o["YR"], o["KN_G"], o["PY"], misc["W_HOURS"], o["N_N"],
                             misc["LOAD"], o["KN_N"], 1994, int(o.index.max()))
    c0, a_g, b_l, g_k, loadmax = pf
    o["GDPMAX"] = np.exp(c0 + a_g * np.log(o["KN_G"] / o["PY"])
                         + b_l * np.log(misc["WHMAX"] * o["N_N"])
                         + g_k * np.log(loadmax * o["KN_N"] / o["PY"]))
    o["GDPGAP"] = (o["YR"] - o["GDPMAX"]) / o["GDPMAX"] * 100
    print("   生産関数（1994-%d年度 OLS）: 政府資本 %.4f / 労働 %.4f / 稼働率×資本 %.4f, LOADmax %.2f"
          % (int(o.index.max()), a_g, b_l, g_k, loadmax))
    print("   （論文 0.3704 / 0.5927 / 0.1249, LOADmax 135.6667）")
    print("   名目需要項目・部門別フロー・純資産・GDPギャップなど %d 系列" % 60)
    print("   GDPギャップ 最終年度 %.2f%%（内閣府公表と水準は一致しない）"
          % o["GDPGAP"].iloc[-1])

    print("\n[8] 検算")
    # 名目GDP = 実質GDP × GDPデフレータ
    gap = (o["YN"] - o["YR"] * o["PY"]).abs() / o["YN"] * 100
    print("   YN と YR*PY の差（％）: 最大 %.3f" % gap.max())
    if gap.max() > 0.5:
        fail.append("YN と YR*PY が合わない")
    # 失業率が妥当な範囲か
    unr = o["UNR"] / 100.0
    print("   失業率: %.2f%% - %.2f%%" % (unr.min() * 100, unr.max() * 100))
    if not (0.01 < unr.min() and unr.max() < 0.08):
        fail.append("失業率が不自然")

    o = o.sort_index()
    o.index.name = "年度"
    print("=" * 74)
    if fail:
        # 検算に落ちたときは書かない。前回の正常な CSV を残す（fetch_misc.py と同じ）
        print("検算に失敗:", ", ".join(fail))
        print("   japan_endo_fy.csv は書き換えていない")
        return 1
    o.round(6).to_csv("japan_endo_fy.csv", encoding="utf-8-sig")
    print("   japan_endo_fy.csv  %d年度 × %d系列 (%d-%d)"
          % (len(o), o.shape[1], o.index.min(), o.index.max()))
    print("完了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
