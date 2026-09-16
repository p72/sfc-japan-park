"""fetch_fincome.py -- 金利・配当率と、それを使う残りの外生変数を作る。

朴(2025c) のモデルは各部門の利子・配当の純所得を

    FINCOME_X = rH*GSH + rB*GB + rM*DEP + rL*LBD + chi*EQU + psi*PEN

と定義している（本体 4.1）。変数表は rB / rM / rL / chi / psi の出典を
「SNA データより計算」とだけ書いており、作り方は書かれていない。ここでは
「その商品を主に持つ（あるいは発行する）部門の利子・配当 ÷ その商品の残高」
として求める。国民経済計算の財産所得は商品別に分かれていないので、
部門を使って切り分けるほかない。

    rB   一般政府の支払利子 / 国債発行額 −NGBA_G（純額）           本体 2章
    rM   家計の受取利子     / 家計の預金 NDEPA_H                    本体 2章
    rL   金融機関の受取利子 / 金融機関の融資債券純保有 NLBDA_F      本体 2章
    chi  非金融法人の配当純受取 / 前期の NEQUA_N（純額）        本体 2章
    psi  金融機関の純保険年金所得 / 前期の NPENA_F（純額）      本体 2章

chi と psi は本体 2章が作り方を明記している。「その資産の発行者として最も
重要な部門」を選ぶという方針で、株式は非金融法人、保険年金は金融機関である。
  chi: 法人企業＋非営利団体の「(2)法人企業の分配所得」「(3)海外直接投資に
       関する再投資収益」の受取から支払を引いた純配当（支払超で負値）を、
       前期の純株式資産（負値）で割る
  psi: 金融機関の「a.保険契約者に帰属する投資所得」の受取から、支払側の
       「a」と「b.年金受給権に係る投資所得」の合計を引いた純保険年金所得
       （負値）を、前期の純保険年金資産（負値）で割る

時点の取り方は本体 2章のとおり2通りある。
  金利 rB / rM / rL:  r_t = 利子_{t+1} ÷ 残高_t
      「ある年度に受け払いされる利子は、前年度に決まった金利と前年度末の
      ストックの積」という考え方。翌年度の利子が無い最終年度は前年度の値で
      代用する（論文も 2023年度を 2022年度の値で代用している）
  配当率 chi / psi:   r_t = 純所得_t ÷ 残高_{t-1}
どちらも FINCOME_t = r_{t-1}·残高_{t-1} + chi_t·残高_{t-1} + … に入る（本体 2章の
定義式）ので、金利は「今年度の利子 ÷ 前年度末残高」で今年度の所得を再現する。
論文が例示する 1994年度の rB = 0.0754393 に対し、この作り方で 0.0756 になる
（差はデータの版の違い）。

この FINCOME は実際の財産所得とはかなり違う値になる。論文もそれを承知の上で
差を EPSILON_X で吸収しており、「epsilon_F は近年になるほど値が大きくなる。
それは主に配当純受取の実績値と計算値との差が近年になるほど大きくなるため」と
書いている（本体 4.3）。

出力: japan_fincome_fy.csv
"""
import os
import sys

import pandas as pd

import fetch_sector as fs

FY = fs.FY
SECTORS = ["N", "CB", "F", "G", "H", "W"]
TYPES = ["GSH", "GB", "DEP", "LBD", "EQU", "PEN"]


def main():
    print("=" * 74)
    print("金利・配当率と FINCOME、EPSILON（国民経済計算 %d年度確報）" % FY)
    print("=" * 74)
    fail = []

    print("\n[1] 金利・配当率")
    h_recv = fs.read_sna_sided("%di5_jp.xlsx" % FY, "年度（１）")
    f_recv = fs.read_sna_sided("%di3_jp.xlsx" % FY, "年度（１）")
    f_pay = fs.read_sna("%di3_jp.xlsx" % FY, "年度（１）")
    g_pay = fs.read_sna("%di4_jp.xlsx" % FY, "年度（１）")
    n1_recv = fs.read_sna_sided("%di2_jp.xlsx" % FY, "年度（１）")
    n1_pay = fs.read_sna("%di2_jp.xlsx" % FY, "年度（１）")
    n2_recv = fs.read_sna_sided("%di6_jp.xlsx" % FY, "年度（１）")
    # 純額の残高（資産−負債）。chi と psi の分母は本体 2章どおり純額を使う
    st = pd.read_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "japan_ff_stock_fy.csv"), index_col=0, encoding="utf-8-sig")

    # 非金融法人の配当純受取。法人企業は (2)+(3) の受取−支払、非営利団体は
    # 受取の「(2)配当」だけ（支払側に配当の項目が無い）。支払超なので負値。
    net_div_n = (fs.pick(n1_recv, "（２）法人企業の分配所得")
                 + fs.pick(n1_recv, "（３）海外直接投資に関する再投資収益")
                 + fs.pick(n2_recv, "（２）配当")
                 - fs.pick(n1_pay, "（２）法人企業の分配所得")
                 - fs.pick(n1_pay, "（３）海外直接投資に関する再投資収益"))
    # 金融機関の純保険年金所得。受取 a から支払 a+b を引く。支払超なので負値。
    pen_f = (fs.pick(f_recv, "ａ．保険契約者に帰属する投資所得")
             - fs.pick(f_pay, "ａ．保険契約者に帰属する投資所得")
             - fs.pick(f_pay, "ｂ．年金受給権に係る投資所得"))

    def lead_rate(interest, stock):
        # 本体 2章: r_t = 利子_{t+1} ÷ 残高_t。最終年度は前年度の値で代用
        rate = interest.shift(-1) / stock
        rate.loc[FY] = rate.loc[FY - 1]
        return rate

    r = pd.DataFrame()
    r["RB"] = lead_rate(fs.pick(g_pay, "（１）利子"), -st["NGBA_G"])
    r["RM"] = lead_rate(fs.pick(h_recv, "（１）利子"), st["NDEPA_H"])
    r["RL"] = lead_rate(fs.pick(f_recv, "（１）利子"), st["NLBDA_F"])
    r["CHI"] = net_div_n / st["NEQUA_N"].shift(1)       # 負値 ÷ 負値
    r["PSI"] = pen_f / st["NPENA_F"].shift(1)           # 負値 ÷ 負値
    r["RH"] = 0.0                       # 現金・HPM には利子を付けない（本体 4.1）
    print("   配当純受取（N）最終年度 %.1f 十億円、純保険年金所得（F）%.1f 十億円（どちらも負が正常）"
          % (net_div_n.iloc[-1], pen_f.iloc[-1]))
    for c in ["RB", "RM", "RL", "CHI", "PSI"]:
        v = r[c].loc[1995:]
        print("   %-4s 1995年度 %.4f → 最終年度 %.4f （範囲 %.4f - %.4f）"
              % (c, v.iloc[0], v.iloc[-1], v.min(), v.max()))
        # chi は N の配当純受取が一時的に受取超になる年（2022年度、円安で海外
        # 再投資収益が膨らんだ）にごく僅かな負になる。ゼロ同然なので通す。
        lo = -0.005 if c == "CHI" else 0.0
        if not (lo <= v.min() and v.max() < 0.20):
            fail.append("%s の水準が不自然（%.4f 〜 %.4f）" % (c, v.min(), v.max()))
        elif v.min() < 0:
            print("        ※ %s が負になる年: %s（ゼロ同然なので通す）"
                  % (c, [int(y) for y in v.index[v < 0]]))

    print("\n[2] FINCOME")
    st = pd.read_csv(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "japan_ff_stock_fy.csv"), index_col=0, encoding="utf-8-sig")
    misc = pd.read_csv("japan_misc_fy.csv", index_col=0, encoding="utf-8-sig")
    fin = pd.DataFrame(index=st.index)
    for sec in SECTORS:
        gsh = st["NGSHA_%s" % sec].shift(1)
        if sec == "CB":
            gsh = gsh - misc["GOLD"].shift(1)      # 金には利子が付かない（本体 4.2）
        fin["FINCOME_%s" % sec] = (
            r["RH"].shift(1) * gsh
            + r["RB"].shift(1) * st["NGBA_%s" % sec].shift(1)
            + r["RM"].shift(1) * st["NDEPA_%s" % sec].shift(1)
            + r["RL"].shift(1) * st["NLBDA_%s" % sec].shift(1)
            + r["CHI"] * st["NEQUA_%s" % sec].shift(1)
            + r["PSI"] * st["NPENA_%s" % sec].shift(1))
    print("   6部門ぶん計算。合計（本来ゼロに近いはず）最終年度 %.1f 十億円"
          % fin.iloc[-1].sum())

    print("\n[3] 貯蓄の開差 EPSILON")
    a1 = fs.read_sna("%da1_jp.xlsx" % FY, "年度")
    nom = fs.read_sna("%dffm1n_jp.xlsx" % FY, "実数")
    sec_csv = pd.read_csv("japan_sector_fy.csv", index_col=0, encoding="utf-8-sig")

    yn = a1["国内総生産"]
    wb_n = a1["雇用者報酬"]
    b2 = a1["営業余剰・混合所得"] + a1["固定資本減耗"]
    tin_n = a1["生産・輸入品に課される税"] - a1["（控除）補助金"]
    gn = fs.pick(nom, "政府現実最終消費")
    xn = fs.pick(nom, "（１）財貨・サービスの輸出")
    mn = fs.pick(nom, "（２）（控除）財貨・サービスの輸入")

    inc2 = dict((s, fs.read_sna(f, "年度（２）")) for s, f in fs.SEC_FILE.items())
    inc1 = dict((s, fs.read_sna(f, "年度（１）")) for s, f in fs.SEC_FILE.items())
    cap = {}
    for sec, f in fs.CAP_FILE.items():
        d = fs.read_sna(f, "年度（１）資本")
        cap[sec] = dict(S=fs.pick(d, "貯蓄（純）") + fs.pick(d, "（控除）固定資本減耗"),
                        D=fs.pick(d, "（控除）固定資本減耗"))

    def b2_gross(sec):
        d = inc1[sec]
        net = 0.0
        for n in ("営業余剰（純）", "営業余剰・混合所得（純）"):
            if n in d.columns:
                net = d[n]
                break
        return net + cap[sec]["D"]

    b2_sec = dict((s, b2_gross(s)) for s in fs.SEC_FILE)
    b2_n = b2_sec["N1"] + b2_sec["N2"]
    s_n = cap["N1"]["S"] + cap["N2"]["S"]
    td_n = fs.pick(inc2["N1"], "所得・富等に課される経常税（支払）")
    t_g = fs.pick(inc2["G"], "所得・富等に課される経常税（受取）") + tin_n

    ep = pd.DataFrame(index=st.index)
    ep["EPSILON_N"] = s_n - (yn - wb_n + (b2_n - b2) + fin["FINCOME_N"]
                             - tin_n - td_n + sec_csv["STR_N"])
    ep["EPSILON_F"] = cap["F"]["S"] - (b2_sec["F"] + fin["FINCOME_F"]
                                       - sec_csv["T_F"] + sec_csv["STR_F"]
                                       - sec_csv["CPEN_F"])
    # 政府の移転純受取。Gn に政府「現実」最終消費を使う以上、こちらも現物社会移転を
    # 差し引いた調整可処分所得に合わせないと、現物社会移転のぶんだけ食い違う。
    g2 = inc2["G"]
    g3 = fs.read_sna(fs.SEC_FILE["G"], "年度（３）")
    str_g = (fs.pick(g3, "調整可処分所得（純）") - fs.pick(g2, "第１次所得バランス（純）")
             - fs.pick(g2, "所得・富等に課される経常税（受取）"))
    ep["EPSILON_G"] = cap["G"]["S"] - (b2_sec["G"] + fin["FINCOME_G"] + t_g + str_g - gn)

    # 家計は税引き前総所得を使う。論文は「調整可処分所得に所得・富等に課される
    # 経常税を加えたもの」と定義している（本体 4.5）。可処分所得ではない点に注意。
    h2 = inc2["H"]
    h3 = fs.read_sna(fs.SEC_FILE["H"], "年度（３）")
    y_h = (fs.pick(h3, "調整可処分所得（純）") + cap["H"]["D"]
           + fs.pick(h2, "所得・富等に課される経常税（支払）"))
    wb_h = fs.pick(fs.read_sna_sided("%di5_jp.xlsx" % FY, "年度（１）"), "雇用者報酬（受取）")
    inc3_h = fs.read_sna(fs.SEC_FILE["H"], "年度（３）")
    str_h = (fs.pick(h2, "現物社会移転以外の社会給付（受取）")
             + fs.pick(h2, "その他の経常移転（受取）")
             + fs.pick(inc3_h, "現物社会移転（受取）")
             - fs.pick(h2, "その他の経常移転（支払）")
             - fs.pick(h2, "純社会負担（支払）"))
    ep["EPSILON_H"] = y_h - (wb_h + b2_sec["H"] + fin["FINCOME_H"] + str_h)

    row_cur = fs.read_sna("%da4_jp.xlsx" % FY, "年度（１）経常")
    row_recv = fs.read_sna_sided("%da4_jp.xlsx" % FY, "年度（１）経常")
    s_w = fs.pick(row_cur, "経常対外収支")
    wb_w = fs.pick(row_recv, "雇用者報酬（受取）") - fs.pick(row_cur, "雇用者報酬（支払）")
    ep["EPSILON_W"] = s_w - (mn - xn + fin["FINCOME_W"] + wb_w
                             - sec_csv["T_W"] + sec_csv["STR_W"])
    for c in ep.columns:
        print("   %-11s 最終年度 %10.1f 十億円（平均絶対 %9.1f）"
              % (c, ep[c].iloc[-1], ep[c].loc[1996:].abs().mean()))

    print("\n[4] 日本銀行の純貸出ギャップ GAPNL_CB")
    # NL_CB = NNFWA_CB(-1) - CG_CB - NNFWA_CB、GAPNL_CB = NL_CB - FINCOME_CB（本体 4.2）
    cg = pd.read_csv("japan_ff_cg_fy.csv", index_col=0, encoding="utf-8-sig")
    cg_cb = sum(cg["N%sACG_CB" % t] for t in TYPES)
    nl_cb = st["NNFWA_CB"].shift(1) - cg_cb - st["NNFWA_CB"]
    ep["GAPNL_CB"] = nl_cb - fin["FINCOME_CB"]
    print("   GAPNL_CB 最終年度 %.1f 十億円" % ep["GAPNL_CB"].iloc[-1])

    out = pd.concat([r, fin, ep], axis=1).sort_index()
    out.index.name = "年度"
    if not fail:
        # 検算に落ちたときは書かない。前回の正常な CSV を残す（fetch_misc.py と同じ）
        out.round(6).to_csv("japan_fincome_fy.csv", encoding="utf-8-sig")
        print("\n   japan_fincome_fy.csv  %d年度 × %d系列 (%d-%d)"
              % (len(out), out.shape[1], out.index.min(), out.index.max()))
    print("=" * 74)
    if fail:
        print("検算に失敗:", ", ".join(fail))
        print("   japan_fincome_fy.csv は書き換えていない")
        return 1
    print("完了")
    return 0


if __name__ == "__main__":
    sys.exit(main())
