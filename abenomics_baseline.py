"""abenomics_baseline.py -- 反実仮想のベースライン（シナリオ1）を図にする。

  python abenomics_baseline.py

WP65 4.1 は「外生変数はすべてデータセットに含まれる実績値であり、内生変数は
ファイナルテストの結果と同じものである。2010 年度から 2023 年度の期間について
ベースラインの計算を走らせた」と書いている。その計算を実績と並べる。

図は上段が水準9本、下段が比率・ギャップ4本。単位も桁も性格が違うので分けた。
論文 表6 の公表値との突き合わせは、図ではなく実行時の表で出す。

ベースラインは各シナリオの比較の土台なので、これが実績から離れていると、
シナリオとの差＝政策の純効果がそのぶん薄まる。だから水準そのものを見ておく。

出力:
  abenomics_baseline_<開始>_<終了>.png
"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from jfont import use_japanese_font
import abenomics_park as ab
import parkmodel as pm

use_japanese_font()

ACT = "#1a1a19"      # 実績。基準として置くインク色（カテゴリ色ではない）
MOD = "#2a78d6"      # 本実装のベースライン。検証済みの categorical slot 1

LO, HI = ab.START, ab.END      # 反実仮想と同じ区間（END はデータの最終年度）

# 朴(2026) WP65 表6「シナリオ1（ベースライン）の計算結果」p.9 を書き写したもの。
# 実行時に本実装との差を表で出すために持っている（図には描かない）。
# 表6 にはこのほか GDP ギャップ・PB 対 GDP 比・政府純貸出 GDP 比・純公債残高
# GDP 比の4行もあるが、PDF からの抽出で単位が合わず（GDP ギャップが％表記で
# -7,651.9 など）読み違えの恐れがあるので、ここには書き写していない。
PAPER_T6 = {
    "YN":    {2013: 530425.4, 2015: 544955.6, 2018: 558841.7, 2020: 558855.3, 2023: 609338.1},
    "YR":    {2013: 535925.8, 2015: 530820.9, 2018: 548964.3, 2020: 540831.7, 2023: 566230.7},
    "IR_N":  {2013: 88697.2, 2015: 89252.3, 2018: 95199.1, 2020: 91123.7, 2023: 100305.7},
    "CR":    {2013: 364654.7, 2015: 358859.9, 2018: 370452.4, 2020: 361282.9, 2023: 375981.6},
    "YDR_H": {2013: 401063.0, 2015: 387346.3, 2018: 403844.1, 2020: 433308.6, 2023: 402082.4},
    "W":     {2013: 42.2, 2015: 43.1, 2018: 42.8, 2020: 42.8, 2023: 45.0},
    "MB":    {2013: 219275.8, 2015: 265099.5, 2018: 367860.9, 2020: 411069.4, 2023: 698457.4},
    "MS":    {2013: 1201641.0, 2015: 1274386.0, 2018: 1379401.0, 2020: 1567791.0, 2023: 1723979.0},
    "PC":    {2013: 0.995, 2015: 1.015, 2018: 1.007, 2020: 1.016, 2023: 1.082},
}

# (変数, 見出し, 単位, 表示倍率)。並びは表6 と同じ。
LEVELS = [
    ("YN",    "名目GDP",       "兆円", 1e-3),
    ("YR",    "実質GDP",       "兆円", 1e-3),
    ("IR_N",  "実質法人投資",   "兆円", 1e-3),
    ("CR",    "実質家計消費",   "兆円", 1e-3),
    ("YDR_H", "実質可処分所得", "兆円", 1e-3),
    ("W",     "名目賃金率",     "十万円/人", 1.0),
    ("MB",    "マネタリーベース", "兆円", 1e-3),
    ("MS",    "マネーストック",  "兆円", 1e-3),
    ("PC",    "消費デフレータ",  "%d年度=1" % pm.deflator_base(), 1.0),
]

# 比率とギャップ。モデルの内生変数から組み立てる。
#
#   GDPGAP   モデルに式がある内生変数。gdpgap = (Yr - GDPMAX) / GDPMAX * 100
#   PB       プライマリーバランス。WP65 は「政府の純貸出から利子の受払いを
#            控除したもの（田村 2014）」とする。FINCOME_G は政府の金融所得の
#            純受取（政府は純支払いなので負）なので、差し引いて求める
#   NL_G     政府の純貸出
#   NGBA_G   政府が保有する国債の純資産。負なら純債務なので符号を反転する
#
# 純公債残高については、WP65 本文が「モデル内で定義された政府の国債・短証の
# 純発行額を名目 GDP で割ったもの」と書いており、表6 の値（-1.8 など）も
# フローに見える。ここでは行の見出しどおり残高の対 GDP 比を描く。
def _ratios(f):
    """水準の系列から、図に出す4つの比率を作る。

    プライマリーバランスの定義は WP65 付録のもの（WP65 付録 p.32-35）。

      PB = NL_G - (rB(-1)*NGBA_G(-1) + rM(-1)*NDEPA_G(-1) + rL(-1)*NLBDA_G(-1)
                   + FINCOME_CB)

    政府の純貸出から利払い（国債・預金・融資の3つ）を戻したものである。
    日銀から政府に移る金融純所得 FINCOME_CB も「一種の利払い」として
    プライマリーバランスの外に置く、というのが WP65 の扱い。
    株式・年金の運用収益と日銀預け金の利息は差し引かないので、
    FINCOME_G をまるごと引くのとは少し違う。"""
    yn = f["YN"]
    interest = (f["RB"].shift(1) * f["NGBA_G"].shift(1)
                + f["RM"].shift(1) * f["NDEPA_G"].shift(1)
                + f["RL"].shift(1) * f["NLBDA_G"].shift(1)
                + f["FINCOME_CB"])
    return {
        "GDPGAP":  f["GDPGAP"],
        "PB_GDP":  (f["NL_G"] - interest) / yn * 100.0,
        "NL_GDP":  f["NL_G"] / yn * 100.0,
        "NGB_GDP": -f["NGBA_G"] / yn * 100.0,
    }


# (キー, 見出し, 2行目)。パネルが狭いので見出しは2行に割る。
RATIOS = [
    ("GDPGAP",  "GDPギャップ",         "％"),
    ("PB_GDP",  "プライマリーバランス", "対GDP比（％）"),
    ("NL_GDP",  "政府純貸出",           "対GDP比（％）"),
    ("NGB_GDP", "純公債残高",           "対GDP比（％）"),
]


def mape(sim, act, v, lo, hi):
    a, s = act[v].loc[lo:hi], sim[v].loc[lo:hi]
    ok = np.isfinite(a) & np.isfinite(s) & (a.abs() > 1e-9)
    return float(((s[ok] - a[ok]).abs() / a[ok].abs() * 100).mean())


def _style(ax, lo, hi):
    ax.grid(True, lw=.5, alpha=.35)
    ax.set_axisbelow(True)
    ax.set_xlim(lo, hi)
    ax.set_xticks(range(lo, hi + 1, 2))
    ax.tick_params(labelsize=9)
    ax.margins(y=.12)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def fig_baseline(d, bl, path):
    yrs = list(range(LO, HI + 1))
    # 上段は水準9本を3列、下段は比率4本を4列。列幅が違うので、共通の
    # 12列グリッドの上に 4列ぶん／3列ぶんで敷く。
    fig = plt.figure(figsize=(13.5, 14.6))
    gs_top = fig.add_gridspec(3, 3, left=.055, right=.985, top=.885, bottom=.255,
                              hspace=.45, wspace=.25)
    gs_bot = fig.add_gridspec(1, 4, left=.055, right=.985, top=.163, bottom=.042,
                              wspace=.30)

    for i, (v, label, unit, scale) in enumerate(LEVELS):
        ax = fig.add_subplot(gs_top[i // 3, i % 3])
        ax.plot(yrs, (d[v].loc[LO:HI] * scale).values, color=ACT, lw=2.0,
                label="実績", zorder=4)
        ax.plot(yrs, (bl[v].loc[LO:HI] * scale).values, color=MOD, lw=2.0,
                ls="--", label="本実装のベースライン", zorder=3)
        ax.set_title("%s（%s）　誤差率 %.2f%%" % (label, unit, mape(bl, d, v, LO, HI)),
                     fontsize=11, pad=8)
        _style(ax, LO, HI)
        if i == 0:
            handles, labels = ax.get_legend_handles_labels()

    ra, rb = _ratios(d), _ratios(bl)
    for i, (k, label, sub) in enumerate(RATIOS):
        ax = fig.add_subplot(gs_bot[0, i])
        a, b = ra[k].loc[LO:HI], rb[k].loc[LO:HI]
        lo_v = min(a.min(), b.min())
        hi_v = max(a.max(), b.max())
        if lo_v < 0 < hi_v:          # ゼロをまたぐときだけ基準線を引く
            ax.axhline(0, color=ACT, lw=1.0, zorder=1)
        ax.plot(yrs, a.values, color=ACT, lw=2.0, zorder=4)
        ax.plot(yrs, b.values, color=MOD, lw=2.0, ls="--", zorder=3)
        # 率どうしの差なので、％の比ではなく％ポイントの差で測る
        gap = float((b - a).abs().mean())
        ax.set_title("%s\n%s　ずれ %.2f%%pt" % (label, sub, gap), fontsize=10, pad=8)
        _style(ax, LO, HI)
        ax.set_xticks(range(LO, HI + 1, 4))

    fig.legend(handles, labels, loc="upper center", bbox_to_anchor=(.5, .945),
               ncol=2, fontsize=10, frameon=False)
    fig.text(.055, .905, "水準", fontsize=10.5, color=ACT, weight="bold")
    fig.text(.055, .207, "比率・ギャップ", fontsize=10.5, color=ACT, weight="bold")
    fig.suptitle("反実仮想のベースライン（シナリオ1）　%d–%d年度　"
                 "外生変数はすべて実績、内生変数はモデルが解いた値" % (LO, HI),
                 fontsize=13, y=.982)
    fig.savefig(path, dpi=130)
    return fig


def main():
    print("=" * 78)
    print("ベースライン（シナリオ1）を %d-%d年度で解いています…" % (ab.START, ab.END))
    print("=" * 78)
    bl = ab.baseline()
    d = pm.data()

    path = "abenomics_baseline_%d_%d.png" % (LO, HI)
    f = fig_baseline(d, bl, path)
    print("\n   %s を保存" % path)

    print("\n   水準の平均絶対誤差率（%d-%d年度）" % (LO, HI))
    print("      %-16s %10s   %s" % ("変数", "誤差率", "論文 表6 との差（%）"))
    for v, label, _u, _s in LEVELS:
        gaps = ["%s %+.1f" % (y, (bl[v].loc[y] / p - 1) * 100)
                for y, p in sorted(PAPER_T6.get(v, {}).items())]
        print("      %-16s %9.2f%%   %s" % (label, mape(bl, d, v, LO, HI),
                                            "  ".join(gaps)))

    ra, rb = _ratios(d), _ratios(bl)
    print("\n   比率・ギャップの平均のずれ（%d-%d年度、%%ポイント）" % (LO, HI))
    print("      %-28s %10s %10s %10s" % ("変数", "平均のずれ", "実績2023", "モデル2023"))
    for k, label, _sub in RATIOS:
        a, b = ra[k].loc[LO:HI], rb[k].loc[LO:HI]
        print("      %-28s %9.2f  %9.2f%% %9.2f%%"
              % (label, float((b - a).abs().mean()), a.loc[HI], b.loc[HI]))
    plt.close(f)
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
