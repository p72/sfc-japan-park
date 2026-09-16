"""contax_panels.py -- 消費税据え置きシナリオを、WP65 の表の項目立てで描く。

  python contax_panels.py [税率]     既定は 5.0（％）

`contax_scenario.py` が6枚の要約図を描くのに対し、こちらは朴(2026) WP65 の
各シナリオ表（表10 以降）と表22 が並べている項目をそのまま24枚にして描く。
中身のシミュレーションは `contax_scenario.run()` と同じものを使う。

【読むときの注意】
図の3本のうち、ベースラインは「実績の税率のままモデルを2010年度から動学で
解いた計算値」であって、実績そのものではない。政策の効果として読めるのは
「2本のモデル線の差」だけで、実績との差ではない。実績の線は、モデルが実績から
どれだけ離れているかを確かめるために置いてある。

既定では失業率に下限を置いていない（論文どおりの UNR = UN/LF*100）。
下限を掛けて走らせたときだけ、張り付いた年に帯が入る。

【論文の範囲外】
WP65 のシナリオ9 は「消費税を予定どおり10%へ」という増税方向で、減税方向は
論文のどこにも無い。これはこちらの拡張である。
"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import abenomics_park as ap
import contax_scenario as cs
import parkmodel as pm
from jfont import use_japanese_font

use_japanese_font()

# 消費デフレータの基準年。確報の版で変わるのでデータから作る
# （2023年度確報は2015年度、2024年度確報は2020年度）。
_PC_BASE = "%d年度=1" % pm.deflator_base()

BN = 1e-3            # 十億円 → 兆円
SECTORS = ["N", "CB", "F", "G", "H", "W"]

# (キー, 見出し, 単位, 表示倍率)。WP65 の表と同じ並び。
# DIFF_NL_G と FNWLR_SUM はモデルの変数ではないので series() で作る。
PANELS = [
    ("YN",         "名目GDP",                  "兆円",        BN),
    ("YR",         "実質GDP",                  "兆円",        BN),
    ("CN",         "名目消費",                  "兆円",        BN),
    ("CR",         "実質消費",                  "兆円",        BN),
    ("XN",         "名目輸出",                  "兆円",        BN),
    ("MN",         "名目輸入",                  "兆円",        BN),
    ("TB",         "名目貿易収支",               "兆円",        BN),
    ("XR",         "実質輸出",                  "兆円",        BN),
    ("MR",         "実質輸入",                  "兆円",        BN),
    ("TBR",        "実質貿易収支",               "兆円",        BN),
    ("PC",         "消費デフレータ",             _PC_BASE,  1.0),
    ("YDR_H",      "実質可処分所得",             "兆円",        BN),
    ("W",          "名目賃金率",                "十万円/人",    1.0),
    ("NL_G",       "政府名目純貸出",             "兆円",        BN),
    ("DIFF_NL_G",  "政府純貸出増分",             "兆円",        BN),
    ("FNWLR_N",    "実質金融純資産 非金融法人",    "兆円",        BN),
    ("FNWLR_CB",   "実質金融純資産 日本銀行",      "兆円",        BN),
    ("FNWLR_F",    "実質金融純資産 金融機関",      "兆円",        BN),
    ("FNWLR_G",    "実質金融純資産 政府",         "兆円",        BN),
    ("FNWLR_H",    "実質金融純資産 家計",         "兆円",        BN),
    ("FNWLR_W",    "実質金融純資産 海外",         "兆円",        BN),
    ("FNWLR_SUM",  "実質金融純資産 合計（＝貨幣用金）", "兆円",   BN),
    ("MB",         "マネタリーベース",            "兆円",        BN),
    ("MS",         "マネーストック",              "兆円",        BN),
]


def series(sim, key, scale):
    """1系列を取り出す。モデルに無い2つはここで組み立てる。"""
    if key == "FNWLR_SUM":
        # 6部門の実質金融純資産の和。定義上ここは貨幣用金に一致する
        # （FNWL_X = -NNFWA_X、Σ NNFWA_X = -GOLD）。恒等式の検算も兼ねる。
        return sum(sim["FNWLR_%s" % s] for s in SECTORS) * scale
    return sim[key] * scale


def figure(bl, s, act, rate, path):
    """実績・ベースライン・シナリオの3本を24項目ぶん描く。"""
    lo, hi = ap.START, ap.END
    yrs = list(range(lo, hi + 1))
    stuck = set(cs.floor_years(s))
    fig, axes = plt.subplots(6, 4, figsize=(17.4, 20.6))

    for ax, (k, label, unit, sc) in zip(axes.ravel(), PANELS):
        for y in stuck:                       # 信頼度が落ちる区間
            ax.axvspan(y - .5, y + .5, color="#c9782e", alpha=.10, lw=0, zorder=0)
        ax.axvline(cs.HIKE - .5, color=cs.BASE, lw=.8, ls=":", alpha=.6, zorder=1)

        if k == "DIFF_NL_G":
            # 増分は「据え置き − ベースライン」の1本。実績は存在しない。
            dif = (series(s, "NL_G", sc) - series(bl, "NL_G", sc)).loc[lo:hi]
            ax.axhline(0, color=cs.BASE, lw=.9, alpha=.5, zorder=2)
            ax.fill_between(yrs, 0, dif.values, color=cs.MOD, alpha=.16,
                            lw=0, zorder=2)
            ax.plot(yrs, dif.values, color=cs.MOD, lw=2.0, zorder=4)
            sub = "据置 − ベース　%+.1f" % dif.loc[hi]
        else:
            r = series(act, k, sc).loc[lo:hi]
            a = series(bl, k, sc).loc[lo:hi]
            b = series(s, k, sc).loc[lo:hi]
            ax.plot(yrs, r.values, color=cs.REAL, lw=1.5,
                    label="実績（統計値）", zorder=2)
            ax.plot(yrs, a.values, color=cs.BASE, lw=2.0,
                    label="ベースライン（モデル計算値）", zorder=3)
            ax.plot(yrs, b.values, color=cs.MOD, lw=2.0, ls="--",
                    label="%g%% のまま据え置き（モデル計算値）" % rate, zorder=4)
            idx = unit.endswith("=1")
            fmt = "%.3f" if idx else "%.1f"
            dfm = "%+.3f" if idx else "%+.1f"
            sub = ("実績 " + fmt + " ／ ベース " + fmt + " → 据置 " + fmt
                   + "（" + dfm + "）") % (r.loc[hi], a.loc[hi], b.loc[hi],
                                          b.loc[hi] - a.loc[hi])

        ax.set_title("%s（%s）\n%s" % (label, unit, sub), fontsize=9.0, pad=7)
        ax.grid(True, lw=.5, alpha=.35)
        ax.set_axisbelow(True)
        ax.set_xlim(lo, hi)
        ax.set_xticks(range(lo, hi + 1, 3))
        ax.tick_params(labelsize=9)
        ax.margins(y=.16)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)

    h, l = axes.ravel()[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", bbox_to_anchor=(.5, .967), ncol=3,
               fontsize=10.5, frameon=False)
    note = ("帯は失業率が下限に張り付いた年＝信頼度が落ちる区間"
            if stuck else "失業率に下限は掛けていない（論文どおりの式）")
    fig.suptitle("消費税が %g%% のままだったら（%d-%d年度）　朴(2026) WP65 の表の項目立てで\n"
                 "政策の効果は「2本のモデル線の差」であって、実績との差ではない。"
                 "各パネル2行目は %d年度の値。%s"
                 % (rate, lo, hi, hi, note), fontsize=13, y=.9955)
    fig.tight_layout(rect=(0, 0, 1, .958))
    fig.savefig(path, dpi=120)
    return fig


def main(argv):
    rate = float(argv[0]) if argv else 5.0
    print("=" * 78)
    print("消費税が %g%% のままだったら（%d-%d年度）　WP65 の項目立てで作図"
          % (rate, ap.START, ap.END))
    print("=" * 78)

    bl, s = cs.run(rate)
    act = pm.data()
    hi = ap.END

    print("\n%d年度の水準（兆円。デフレータと賃金率はそのまま）" % hi)
    print("   %-28s %10s %10s %10s %12s"
          % ("項目", "実績", "ベース", "据え置き", "増分"))
    for k, label, unit, sc in PANELS:
        if k == "DIFF_NL_G":
            continue
        r = float(series(act, k, sc).loc[hi])
        a = float(series(bl, k, sc).loc[hi])
        b = float(series(s, k, sc).loc[hi])
        idx = unit.endswith("=1")
        f = "%10.3f" if idx else "%10.1f"
        g = "%12.3f" if idx else "%12.1f"
        print(("   %-28s " + f + " " + f + " " + f + " " + g)
              % (label, r, a, b, b - a))

    # 恒等式の検算。WP65 表22 の注は「各部門の金融純資産の増分を横方向に
    # 合計すると必ずゼロになる」と書いている。名目では Σ FNWL_X = 貨幣用金 で
    # 外生なので増分はきっかりゼロ。実質は Σ = 貨幣用金 / Pc なので、
    # 消費デフレータが動くぶんだけ残る。
    nom = (sum(s["FNWL_%s" % x] - bl["FNWL_%s" % x]
               for x in SECTORS)).loc[ap.START:hi].abs().max()
    rea = (sum(s["FNWLR_%s" % x] - bl["FNWLR_%s" % x]
               for x in SECTORS)).loc[ap.START:hi].abs().max()
    print("\n   6部門の金融純資産の増分を横に合計（WP65 表22 の注）")
    print("      名目 最大 %.4f 兆円（貨幣用金は外生なのでゼロ）" % (nom * BN))
    print("      実質 最大 %.2f 兆円（貨幣用金 ÷ 消費デフレータ が動くぶん）"
          % (rea * BN))

    p = "contax%g_panels_%d_%d.png" % (rate, ap.START, hi)
    fig = figure(bl, s, act, rate, p)
    plt.close(fig)
    print("   %s を保存（24項目）" % p)

    ub = bl["UNR"].loc[ap.START:hi]
    us = s["UNR"].loc[ap.START:hi]
    print("\n【この結果の限界】")
    print("  失業率の最小値   ベース %.2f%%（%d年度） / 据え置き %.2f%%（%d年度）"
          % (ub.min(), int(ub.idxmin()), us.min(), int(us.idxmin())))
    print("  賃金式の 2.414/UNR は失業率が小さいほど急になる。拡張方向のこの")
    print("  シナリオはそこを強く突くので、賃金・物価の数字は確度が落ちる。")
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
