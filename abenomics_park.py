"""abenomics_park.py -- 朴(2026) WP65 の反実仮想シナリオを、論文モデルで走らせる。

WP65 表5 のシナリオを、同じ操作で再現する。数値は本文の記述に従った。
表5 の要約と本文で食い違うところがあり、そこは本文（導出が書かれている方）を採った。

  2. 利下げなし        2013年度以降 RrB を +1.8%ポイント
                       表5 は「0.75%」だが、本文 4.2 は民主党政権期 2.58% と
                       安倍政権期 0.76% の差 1.82% を四捨五入して 1.8% としている。
  3. 為替レート高止まり 2013年度以降 NEER を +0.2（1基準の指数。率でみて18%）
  4. 株価上昇なし      2012年度以降 株式の評価調整をゼロ
  5. 2012年度補正なし  2012年度のみ 実質政府消費 -6.5兆円、実質政府投資 -6.5兆円
  6. 政府消費の抑制    2013年度以降 実質政府消費 -5兆円
                       表5 は「2014年度以降」だが本文 5.6 は「2013年度以降」
  7. 政府投資の抑制    2013年度以降 実質政府投資 -5兆円
  8. 成長戦略の効果なし 2013年度以降 実質設備投資 -5兆円
  9. 消費税予定通り増税 2015年10月に10%へ（年度平均で2015年度9%、2016年度以降10%）
 10. アベノミクス全効果 2 から 8 の組み合わせ（9 は含めない）

シナリオ8 は実質設備投資が内生変数なので、方程式にアドファクターを足して操作する。
LOG(IR_N) = f を IR_N = EXP(f) + ADJ_IR_N と書き換え、既定はゼロにしてある。

アドファクターに毎年 -5兆円 を入れると、投資式が LOG(IR_N(-1)) を含むため
効果が複利で積み上がり、2023年度には -31.8兆円（-28.2%）まで膨らんでしまう。
論文の言う「実際より5兆円低かった」は水準の差なので、ベースライン比で
ちょうど -5兆円 になるようにアドファクターを繰り返し調整して求める。
求めたアドファクターはシナリオ10 でもそのまま使う。
"""
import os
import re
import sys

import numpy as np
import pandas as pd

import parkmodel as pm
from sfcsim import Model

# WP65 4.1「2010 年度から 2023 年度の期間についてベースラインの計算を走らせた」。
# 起点をここより前に置くと、外生変数を一切いじらないベースラインでも実績からの
# ずれが積み上がり、シナリオとの差（＝政策の純効果）がそのぶん薄まる。実際
# 2005年度起点では名目GDPの反応が論文の7割、賃金が6割まで弱まっていた。
# 論文と同じ 2010年度起点に合わせること。END だけは手持ちのデータの末端まで伸ばす。
START, END = 2010, pm.last_year()
REPORT = [2013, 2015, 2018, 2020, 2023]     # WP65 表20 と同じ年度

# WP65 5.1 が報告するベースラインの平均絶対誤差率（2010-2023年度）。
# こちらのベースラインが同じ水準に収まっているかの目安にする。
PAPER_BASE_MAE = {"YR": 0.71, "PC": 0.44, "W": 1.18}

# 反実仮想は WP65 のものなので、式体系も WP65 版を使う。WP65 付録が明記した
# 朴(2025c) からの変更点（営業余剰の残余式化、日銀の黒字の政府移転、非金融法人
# ポートフォリオ式の差し替え）は parkmodel.WP65_LINES にまとめてある。
# とくに日銀まわりの変更は、利下げシナリオで効く。日銀の金融純所得が動いた分が
# 朴(2025c) では日銀に留まるのに対し、WP65 では全額が政府の純貸出に入る。
WP65 = True

# WP65 表20（シナリオ10、ベースライン比）。pch は％変化、diff は差
PAPER_S10 = {
    "YN":  {2013: -4.9, 2015: -8.6, 2018: -8.7, 2020: -9.1, 2023: -10.9},
    "YR":  {2013: -3.2, 2015: -2.7, 2018: -1.7, 2020: -1.8, 2023: -1.7},
    "IR_N": {2013: -11.2, 2015: -9.9, 2018: -8.6, 2020: -9.6, 2023: -9.2},
    "CR":  {2013: -2.6, 2015: -5.3, 2018: -3.2, 2020: -2.4, 2023: -3.8},
    "W":   {2013: -4.4, 2015: -7.1, 2018: -6.3, 2020: -5.2, 2023: -7.0},
}
PAPER_S10_DIFF = {
    "PC": {2013: -0.020, 2015: -0.046, 2018: -0.038, 2020: -0.033, 2023: -0.051},
}


def with_addfactor(text):
    """実質設備投資にアドファクターを足した方程式体系を返す。"""
    for line in text.split("\n"):
        if re.match(r"^\s*LOG\(\s*IR_N\s*\)\s*=", line, re.I):
            rhs = line.split("=", 1)[1].strip()
            return text.replace(line, "IR_N = EXP(%s) + ADJ_IR_N" % rhs)
    raise ValueError("IR_N の式が見つかりません")


ADJ8 = None          # シナリオ8 のアドファクター。calibrate_s8() が入れる


def calibrate_s8(m, base_data, baseline, target=5000.0, damp=0.4, maxit=40):
    """実質設備投資がベースラインより target だけ低くなるアドファクターを求める。"""
    if isinstance(maxit, bool) or not isinstance(maxit, int) or maxit < 1:
        raise ValueError("maxit は1以上の整数が必要です")
    tgt = baseline["IR_N"] - target
    d = base_data.copy()
    for it in range(maxit):
        sim = m.simulate(d, START, END, mode="dynamic", maxit=5000, tol=1e-7)
        gap = (sim["IR_N"] - tgt).loc[2013:END]
        if gap.abs().max() < 1.0:
            return d.loc[2013:, "ADJ_IR_N"].copy(), it + 1, float(gap.abs().max())
        d.loc[2013:, "ADJ_IR_N"] = (d.loc[2013:, "ADJ_IR_N"]
                                    - damp * gap.reindex(d.loc[2013:].index).fillna(0.0))
    # 収束しなかったものを返すと、呼び出し側が「-5兆円に収まった」と表示して
    # しまい、シナリオ8・10 が目標からずれたまま論文と比較される。止める。
    raise RuntimeError("シナリオ8 のアドファクターが %d 回で収束せず（最大のずれ %.1f 十億円）"
                       % (maxit, float(gap.abs().max())))


def scenarios():
    """(名前, データを書き換える関数) の一覧。"""
    def s2(d):
        d.loc[2013:, "RRB"] += 0.018
    def s3(d):
        d.loc[2013:, "NEER"] += 0.2
    def s4(d):
        for c in [c for c in d.columns if c.startswith("NEQUACG_")]:
            d.loc[2012:, c] = 0.0
    def s5(d):
        d.loc[2012, "GR"] -= 6500.0
        d.loc[2012, "IR_G"] -= 6500.0
    def s6(d):
        d.loc[2013:, "GR"] -= 5000.0
    def s7(d):
        d.loc[2013:, "IR_G"] -= 5000.0
    def s8(d):
        d.loc[2013:, "ADJ_IR_N"] += ADJ8.reindex(d.loc[2013:].index).fillna(0.0)
    def s9(d):
        d.loc[2015, "CONTAX"] = 9.0
        d.loc[2016:, "CONTAX"] = 10.0
    def s10(d):
        for f in (s2, s3, s4, s5, s6, s7, s8):
            f(d)
    return [("1. ベースライン", None),
            ("2. 利下げなし", s2), ("3. 為替レート高止まり", s3),
            ("4. 株価上昇なし", s4), ("5. 2012年度補正なし", s5),
            ("6. 政府消費の抑制", s6), ("7. 政府投資の抑制", s7),
            ("8. 成長戦略の効果なし", s8), ("9. 消費税予定通り増税", s9),
            ("10. アベノミクス全効果", s10)]


def build(wp65=WP65):
    """モデルとベースライン用のデータを組み立てて返す。"""
    text = pm.equations(version=1, coeffs="reest",
                        unr_floor=pm.UNR_FLOOR_DEFAULT, wp65=wp65)
    m = Model(with_addfactor(text), fold_case=True)
    m.accept = pm.accept_solution      # 失業者数が負の解を弾く（parkmodel 参照）
    d = pm.data()
    if wp65:
        d = pm.wp65_residuals(d)
    d["ADJ_IR_N"] = 0.0
    if pm.UNR_FLOOR_DEFAULT is not None:
        d["UNR_FLOOR"] = pm.UNR_FLOOR_DEFAULT
    return m, d


def baseline(wp65=WP65):
    """ベースライン（シナリオ1）だけを解く。

    シナリオ8 のアドファクター較正は要らないので、10シナリオ全部を走らせる
    run_all() よりずっと速い。ベースラインの水準だけ見たいときはこちら。"""
    m, d = build(wp65)
    return m.simulate(d, START, END, mode="dynamic", maxit=5000, tol=1e-7)


def run_all(verbose=True, wp65=WP65):
    """10シナリオを走らせて {シナリオ名: 解} を返す。図のスクリプトからも使う。"""
    def say(*a):
        if verbose:
            print(*a)

    m, base_data = build(wp65)

    say("\n[準備] シナリオ8 のアドファクターを較正する")
    bl0 = m.simulate(base_data, START, END, mode="dynamic", maxit=5000, tol=1e-7)
    global ADJ8
    runs, failed = {}, []
    try:
        ADJ8, nit, gap = calibrate_s8(m, base_data, bl0)
        say("   反復 %d 回で、実質設備投資のベースライン比が -5兆円 に収まった"
            "（最大のずれ %.2f 十億円）" % (nit, gap))
    except RuntimeError as ex:
        # アドファクターが決まらなければ、それを使う 8 と 10 は走らせない
        ADJ8 = None
        say("   %s" % ex)
        for name in ("8. 成長戦略の効果なし", "10. アベノミクス全効果"):
            failed.append((name, "アドファクター未収束のため実行せず"))

    for name, fn in scenarios():
        if any(name == f[0] for f in failed):
            continue
        d = base_data.copy()
        if fn is not None:
            fn(d)
        try:
            runs[name] = m.simulate(d, START, END, mode="dynamic", maxit=5000, tol=1e-7)
        except Exception as ex:
            failed.append((name, str(ex)[:70]))
    say("\n走ったシナリオ: %d / %d" % (len(runs), len(scenarios())))
    for name, msg in failed:
        say("   解けず: %-22s %s" % (name, msg))
    return runs, failed


# アドファクターを入れた1本ぶんの差。sanity_park の [0] に渡す。
_ADDFACTOR_REMOVED = ["LOG(IR_N)=#+#*LOG(IR_N(-1))+#*@PCH(YR)+#*RRL+#*DUM2009"]
_ADDFACTOR_ADDED = ["IR_N=EXP(#+#*LOG(IR_N(-1))+#*@PCH(YR)+#*RRL+#*DUM2009)+ADJ_IR_N"]


def check_equations(wp65=WP65):
    """走らせる式が、論文（と WP65 の変更点）から離れていないかを確かめる。

    ここで許すのは、WP65 が明記した変更点と、シナリオ8 のための
    アドファクター1本だけである。"""
    import sanity_park as sp
    keep = (sp.KNOWN_REMOVED[:], sp.KNOWN_ADDED[:])
    sp.KNOWN_REMOVED = sp.KNOWN_REMOVED + _ADDFACTOR_REMOVED
    sp.KNOWN_ADDED = sp.KNOWN_ADDED + _ADDFACTOR_ADDED
    try:
        text = with_addfactor(pm.equations(version=1, coeffs="reest",
                                           unr_floor=pm.UNR_FLOOR_DEFAULT,
                                           wp65=wp65))
        ok = sp.check_equations(text, wp65=wp65)
        if ok:
            print("       ＋ シナリオ8 のためのアドファクター1本（IR_N）")
        return ok
    finally:
        sp.KNOWN_REMOVED, sp.KNOWN_ADDED = keep


def main():
    print("=" * 78)
    print("WP65 の反実仮想シミュレーション（%d-%d年度）" % (START, END))
    print("=" * 78)
    if not check_equations():
        print("\n方程式が論文から変わっているので、ここで止める。")
        return 1
    try:
        runs, failed = run_all()
    except RuntimeError as ex:
        print("計算失敗: %s" % ex)
        return 1
    if failed or set(runs) != {name for name, _ in scenarios()}:
        print("未完了のシナリオがあるため、結果を保存しません。")
        return 1
    if "1. ベースライン" not in runs:
        print("ベースラインが解けないので比較できない。")
        return 1
    bl = runs["1. ベースライン"]

    print("\nベースラインの平均絶対誤差率（%d-%d年度）" % (START, END))
    act = pm.data()
    print("   %-14s %8s %8s" % ("変数", "論文", "本実装"))
    for v in ["YR", "PC", "W"]:
        a, sm = act[v].loc[START:END], bl[v].loc[START:END]
        ok = np.isfinite(a) & np.isfinite(sm) & (a.abs() > 1e-9)
        print("   %-14s %7.2f%% %7.2f%%"
              % (v, PAPER_BASE_MAE[v],
                 float(((sm[ok] - a[ok]).abs() / a[ok].abs() * 100).mean())))

    print("\nベースラインの水準（WP65 表6 と比べる）")
    print("   %-26s %s" % ("", "  ".join("%9d" % y for y in REPORT)))
    for v, lab in [("YN", "名目GDP [十億円]"), ("YR", "実質GDP [十億円]"),
                   ("IR_N", "実質法人投資 [十億円]"), ("CR", "実質家計消費 [十億円]"),
                   ("W", "名目賃金率 [十万円/人]"), ("PC", "消費デフレータ")]:
        print("   %-26s %s" % (lab, "  ".join("%9.1f" % bl[v].loc[y] for y in REPORT)))

    print("\n各シナリオの実質GDP（ベースライン比 %）")
    print("   %-24s %s" % ("シナリオ", "  ".join("%7d" % y for y in REPORT)))
    for name in runs:
        if name.startswith("1."):
            continue
        ch = [(runs[name]["YR"].loc[y] / bl["YR"].loc[y] - 1) * 100 for y in REPORT]
        print("   %-24s %s" % (name, "  ".join("%7.1f" % c for c in ch)))

    s10 = [n for n in runs if n.startswith("10.")]
    if s10:
        r = runs[s10[0]]
        print("\nシナリオ10 を WP65 表20 と突き合わせる（ベースライン比 %）")
        print("   %-14s %-8s %s" % ("変数", "", "  ".join("%7d" % y for y in REPORT)))
        for v in ["YN", "YR", "IR_N", "CR", "W"]:
            mine = [(r[v].loc[y] / bl[v].loc[y] - 1) * 100 for y in REPORT]
            print("   %-14s %-8s %s" % (v, "論文",
                  "  ".join("%7.1f" % PAPER_S10[v][y] for y in REPORT)))
            print("   %-14s %-8s %s" % ("", "本実装", "  ".join("%7.1f" % c for c in mine)))
        for v in PAPER_S10_DIFF:
            mine = [r[v].loc[y] - bl[v].loc[y] for y in REPORT]
            print("   %-14s %-8s %s" % (v + "(差)", "論文",
                  "  ".join("%7.3f" % PAPER_S10_DIFF[v][y] for y in REPORT)))
            print("   %-14s %-8s %s" % ("", "本実装", "  ".join("%7.3f" % c for c in mine)))

        loss = float(((bl["YR"] - r["YR"]).loc[2012:2023]).sum())   # 論文 5.9節と同じ期間
        print("\n   2012-2023年度の累計実質GDP損失: %.1f 兆円（論文 138.5 兆円）"
              % (loss / 1000.0))

    out = pd.concat([runs[n]["YR"].rename(n) for n in runs], axis=1)
    out.round(2).to_csv("abenomics_park.csv", encoding="utf-8-sig")
    print("\n   abenomics_park.csv に保存した")
    print("=" * 78)
    if failed:
        print("解けなかったシナリオが %d 本ある（上を見ること）" % len(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
