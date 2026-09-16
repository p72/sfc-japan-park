"""contax_scenario.py -- 消費税率を据え置いたら、という反実仮想。

  python contax_scenario.py [税率]     既定は 5.0（％）

実績では 2013年度まで5%、2014年度から8%、2019年度に9%（10月に10%へ）、
2020年度以降10%。これを指定した税率のまま据え置いて解き直し、
ベースラインと比べる。

【論文の範囲外】
朴(2026) WP65 のシナリオ9 は「消費税を予定どおり（4年早く）10%へ」という
増税方向の反実仮想で、減税方向はどこにも無い。こちらの拡張である。

【読むときの注意 その1】
図の3本のうち、ベースラインは「実績の税率のままモデルを2010年度から動学で
解いた計算値」であって、実績そのものではない。2023年度確報では最終年度で
実質GDPが実績より13兆円高く、名目GDPは2兆円低い（平均誤差率 1.4% / 1.2%）。
政策の効果として読めるのは「ベースラインとシナリオの差」だけで、
実績との差ではない。実績の線は、その離れ具合を確かめるために置いてある。

【読むときの注意 その2】
このシナリオはモデルを拡張方向に強く押すので、失業率がかなり低いところまで
下がる。賃金式の 2.414/UNR は失業率が小さいほど急になるため、その領域の
賃金・物価の反応は外挿に近く、確度が落ちる。どこまで下がったかは main() の
最後に出る。

失業率に下限は置かない。論文どおりの UNR = UN/LF*100 のまま解ける（発散は
ソルバーの都合で、sfcsim が発散した年を減衰を強めて解き直す）。
"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

import abenomics_park as ap
import parkmodel as pm
from jfont import use_japanese_font

use_japanese_font()

REAL = "#8a8f94"     # 実績。参照として薄く置く
BASE = "#1a1a19"     # ベースライン（モデル計算値）。基準のインク色
MOD  = "#2a78d6"     # シナリオ。検証済みの categorical slot 1

HIKE = 2014          # 増税が始まった年度

# (キー, 見出し, 単位, 表示倍率)。None は比率として別に計算する
PANELS = [
    ("YR",    "実質GDP",        "兆円", 1e-3),
    ("CR",    "実質家計消費",    "兆円", 1e-3),
    ("PC",    "消費デフレータ",  "%d年度=1" % pm.deflator_base(), 1.0),
    ("YN",    "名目GDP",        "兆円", 1e-3),
    ("TIN_N", "純間接税",        "兆円", 1e-3),
    ("NGB_GDP", "純公債残高対GDP比", "％", None),
]


def series(sim, key, scale):
    if scale is not None:
        return sim[key] * scale
    if key == "NGB_GDP":
        return -sim["NGBA_G"] / sim["YN"] * 100.0
    raise KeyError(key)


def run(rate):
    """ベースラインと据え置きシナリオを解いて返す。"""
    m, base = ap.build()                       # WP65版の式・2010年度起点
    bl = m.simulate(base, ap.START, ap.END, mode="dynamic", maxit=5000, tol=1e-7)
    d = base.copy()
    d.loc[HIKE:, "CONTAX"] = rate
    # 2014年度の増税ダミーは「5% → 8% の引き上げ」のショックなので、その
    # シナリオの税率経路に 2014年度の引き上げが無いときだけ消す。5%据え置き
    # なら消え、8%据え置きなら残る（税率によらず消すと、
    # 8%据え置きで税率が同じ 2014-2018年度にも差が出る）。
    # TIN_N と CR の2本にしか入っていないので、影響はその2本に限られる。
    d.loc[HIKE, "DUM2014"] = hike_dummy(d, HIKE)
    s = m.simulate(d, ap.START, ap.END, mode="dynamic", maxit=5000, tol=1e-7)
    return bl, s


def hike_dummy(d, year=HIKE):
    """税率経路 d["CONTAX"] に year 年度の引き上げがあれば 1、無ければ 0。"""
    return 1.0 if float(d.loc[year, "CONTAX"]) > float(d.loc[year - 1, "CONTAX"]) else 0.0


def floor_years(sim, floor=pm.UNR_FLOOR_DEFAULT):
    """失業率が下限に張り付いた年度。下限を置いていなければ空になる。"""
    if floor is None:
        return []
    u = sim["UNR"].loc[ap.START:ap.END]
    return [int(y) for y in u.index[u <= floor + 1e-9]]


def figure(bl, s, act, rate, path):
    """実績・ベースライン・シナリオの3本を描く。

    政策の効果は「ベースラインとシナリオの差」であって、実績との差ではない。
    ベースラインは実績そのものではなくモデルの計算値なので、実績も並べて
    どれだけ離れているかが見えるようにしておく。"""
    lo, hi = ap.START, ap.END
    yrs = list(range(lo, hi + 1))
    stuck = set(floor_years(s))
    fig, axes = plt.subplots(2, 3, figsize=(13.5, 8.2))
    for ax, (k, label, unit, sc) in zip(axes.ravel(), PANELS):
        r = series(act, k, sc).loc[lo:hi]
        a, b = series(bl, k, sc).loc[lo:hi], series(s, k, sc).loc[lo:hi]
        # 失業率が下限に張り付いた年は薄く塗る（結果の信頼度が落ちる区間）
        for y in stuck:
            ax.axvspan(y - .5, y + .5, color="#c9782e", alpha=.10, lw=0, zorder=0)
        ax.axvline(HIKE - .5, color=BASE, lw=.8, ls=":", alpha=.6, zorder=1)
        ax.plot(yrs, r.values, color=REAL, lw=1.6, label="実績（統計値）", zorder=2)
        ax.plot(yrs, a.values, color=BASE, lw=2.0,
                label="ベースライン（モデル計算値）", zorder=3)
        ax.plot(yrs, b.values, color=MOD, lw=2.0, ls="--",
                label="%g%% のまま据え置き（モデル計算値）" % rate, zorder=4)
        ax.set_title("%s（%s）\n%d年度  実績 %.1f ／ ベース %.1f → 据え置き %.1f（%+.1f）"
                     % (label, unit, hi, r.loc[hi], a.loc[hi], b.loc[hi],
                        b.loc[hi] - a.loc[hi]), fontsize=9.5, pad=8)
        ax.grid(True, lw=.5, alpha=.35)
        ax.set_axisbelow(True)
        ax.set_xlim(lo, hi)
        ax.set_xticks(range(lo, hi + 1, 3))
        ax.tick_params(labelsize=9)
        ax.margins(y=.16)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    h, l = axes.ravel()[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", bbox_to_anchor=(.5, .945), ncol=3,
               fontsize=9.5, frameon=False)
    note = ("帯は失業率が下限に張り付いた年＝結果の信頼度が落ちる区間"
            if stuck else "失業率に下限は掛けていない（論文どおりの式）")
    fig.suptitle("消費税が %g%% のままだったら（%d-%d年度）　政策の効果は"
                 "「2本のモデル線の差」であって、実績との差ではない\n%s"
                 % (rate, lo, hi, note), fontsize=12, y=.997)
    fig.tight_layout(rect=(0, 0, 1, .915))
    fig.savefig(path, dpi=130)
    return fig


def main(argv):
    rate = float(argv[0]) if argv else 5.0
    print("=" * 78)
    print("消費税が %g%% のままだったら（%d-%d年度）" % (rate, ap.START, ap.END))
    print("=" * 78)
    bl, s = run(rate)

    # 2年おきに並べ、最後はデータの最終年度にする（確報の版で変わる）
    yrs = sorted(set([y for y in range(HIKE, ap.END, 2)] + [ap.END]))[-6:]
    print("\nベースライン比（％。デフレータと失業率は差）")
    print("   %-14s %s" % ("変数", "".join("%9d" % y for y in yrs)))
    for k, label in [("YN", "名目GDP"), ("YR", "実質GDP"), ("CR", "実質家計消費"),
                     ("PC", "消費デフレータ"), ("W", "名目賃金率"),
                     ("IR_N", "実質法人投資"), ("N_N", "就業者数"),
                     ("UNR", "失業率"), ("TIN_N", "純間接税")]:
        row = []
        for y in yrs:
            a, b = bl[k].loc[y], s[k].loc[y]
            row.append(b - a if k in ("PC", "UNR") else (b / a - 1) * 100)
        print("   %-14s %s" % (label, "".join("%9.2f" % x for x in row)))

    act = pm.data()
    print("\n%d年度の水準。ベースラインは実績そのものではなくモデルの計算値なので、"
          "実績も並べておく" % ap.END)
    print("   %-14s %10s %10s %10s %14s"
          % ("", "実績", "ベース", "据え置き", "据え置き-ベース"))
    for k, label, sc in [("YR", "実質GDP", 1e-3), ("CR", "実質家計消費", 1e-3),
                         ("YN", "名目GDP", 1e-3), ("TIN_N", "純間接税", 1e-3),
                         ("NL_G", "政府純貸出", 1e-3)]:
        r, a, b = (act[k].loc[ap.END] * sc, bl[k].loc[ap.END] * sc,
                   s[k].loc[ap.END] * sc)
        print("   %-14s %10.1f %10.1f %10.1f %14.1f" % (label, r, a, b, b - a))
    f = lambda d: -d["NGBA_G"].loc[ap.END] / d["YN"].loc[ap.END] * 100
    print("   %-14s %10.1f %10.1f %10.1f %14.1f"
          % ("純公債残高/GDP", f(act), f(bl), f(s), f(s) - f(bl)))

    print("\n%d-%d年度の累計（兆円）" % (HIKE, ap.END))
    for k, label in [("YR", "実質GDP"), ("TIN_N", "純間接税"), ("NL_G", "政府純貸出")]:
        print("   %-14s %+8.1f" % (label, (s[k] - bl[k]).loc[HIKE:ap.END].sum() / 1e3))

    p = "contax%g_%d_%d.png" % (rate, ap.START, ap.END)
    fig = figure(bl, s, pm.data(), rate, p)
    plt.close(fig)
    print("\n   %s を保存" % p)

    ub, us = bl["UNR"].loc[ap.START:ap.END], s["UNR"].loc[ap.START:ap.END]
    print("""
【この結果の限界】
  失業率の最小値   ベース %.2f%%（%d年度） / 据え置き %.2f%%（%d年度）
  賃金式の 2.414/UNR は失業率が小さいほど急になる。拡張方向のこのシナリオは
  失業率をかなり低いところまで押し下げるので、その領域の賃金・物価の反応は
  外挿に近く、確度が落ちると考えること。
  朴(2026) WP65 の反実仮想はすべて収縮方向なので、この問題は起きない。""" %
          (ub.min(), int(ub.idxmin()), us.min(), int(us.idxmin())))
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
