"""park_restart.py -- 「途中の年から回すと楽になる」ことを図で確かめる。

  python park_restart.py            2013年度起点と1997年度起点を 2013-2020年度で比べる
  python park_restart.py 2013 2020  起点年と終わりを指定する

ファイナルテスト（動学シミュレーション）は、起点の前年だけラグ項に実績を使い、
そこから先は自分が計算した値を次の年のラグに渡していく。だから誤差は年を追って
積み上がる。起点を後ろにずらすと、

  ・ラグに実績が入る年（＝タダで正解をもらえる年）が観測したい期間の直前に来る
  ・誤差が積み上がる年数が短くなる

ので、同じ期間を見ても当てはまりが良くなる。モデルが良くなったわけではない。
この差を測って図にするのがこのスクリプト。

出力:
  park_restart_2013_2020.png        実績・1997年度起点・2013年度起点の3本
  park_restart_error_2013_2020.png  同じ期間で測った誤差率の比較
  park_restart_drift_2013_2020.png  起点からの経過年数と誤差率の関係
"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from jfont import use_japanese_font
import parkmodel as pm
from park_plot import PANELS, mape

use_japanese_font()

ACT = "#1a1a19"      # 実績。基準として置くインク色（カテゴリ色ではない）
LONG = "#2a78d6"     # 通しで走らせたほう。検証済みの categorical slot 1
SHORT = "#eb6834"    # 途中から回し直したほう。同 slot 2

FULL_START, FULL_END = 1997, pm.last_year()


def simulate(m, d, lo, hi):
    return m.simulate(d, lo, hi, mode="dynamic", maxit=5000, tol=1e-7)


def fig_paths(d, long_sim, short_sim, lo, hi, path):
    yrs = list(range(lo, hi + 1))
    fig, axes = plt.subplots(4, 3, figsize=(13.5, 13.0))
    for ax, (v, label, unit, scale) in zip(axes.ravel(), PANELS):
        ax.plot(yrs, (d[v].loc[lo:hi] * scale).values, color=ACT, lw=2.0,
                label="実績", zorder=4)
        ax.plot(yrs, (long_sim[v].loc[lo:hi] * scale).values, color=LONG, lw=2.0,
                ls="--", label="%d年度起点（通し）" % FULL_START, zorder=3)
        ax.plot(yrs, (short_sim[v].loc[lo:hi] * scale).values, color=SHORT, lw=2.0,
                ls=":", label="%d年度起点（回し直し）" % lo, zorder=2)
        ax.set_title("%s（%s）　誤差率 %.2f%% → %.2f%%"
                     % (label, unit, mape(long_sim, d, v, lo, hi),
                        mape(short_sim, d, v, lo, hi)), fontsize=11, pad=8)
        ax.grid(True, lw=.5, alpha=.35)
        ax.set_axisbelow(True)
        ax.set_xlim(lo, hi)
        ax.set_xticks(range(lo, hi + 1, 1 if hi - lo <= 8 else 2))
        ax.tick_params(labelsize=9)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    h, l = axes.ravel()[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", bbox_to_anchor=(.5, .958), ncol=3,
               fontsize=10, frameon=False)
    fig.suptitle("同じ %d–%d年度を、起点を変えて解いた結果　"
                 "起点を後ろにずらすと多くの変数で実績に近づくが、モデルが良くなったわけではない"
                 % (lo, hi), fontsize=13, y=.992)
    fig.tight_layout(rect=(0, 0, 1, .952))
    fig.savefig(path, dpi=130)
    return fig


def fig_error(d, long_sim, short_sim, lo, hi, path):
    rows = []
    for v, label, unit, scale in PANELS:
        rows.append((label, mape(long_sim, d, v, lo, hi),
                     mape(short_sim, d, v, lo, hi)))
    rows.sort(key=lambda r: r[1])
    y = np.arange(len(rows))
    h = 0.38
    fig, ax = plt.subplots(figsize=(10.0, 6.8))
    ax.barh(y + h / 2, [r[1] for r in rows], height=h, color=LONG,
            label="%d年度起点（通し）" % FULL_START)
    ax.barh(y - h / 2, [r[2] for r in rows], height=h, color=SHORT,
            label="%d年度起点（回し直し）" % lo)
    for i, r in enumerate(rows):
        for val, off in ((r[1], h / 2), (r[2], -h / 2)):
            ax.text(val + .25, i + off, "%.1f" % val, va="center",
                    fontsize=8.5, color=ACT)
    ax.set_yticks(y, [r[0] for r in rows], fontsize=10)
    ax.set_xlabel("%d–%d年度の平均絶対誤差率（％、小さいほど実績に近い）" % (lo, hi),
                  fontsize=10)
    ax.set_xlim(0, max(max(r[1], r[2]) for r in rows) * 1.16)
    ax.grid(True, axis="x", lw=.5, alpha=.35)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.legend(loc="lower right", fontsize=10, frameon=False)
    down = sum(1 for r in rows if r[2] < r[1])
    ax.set_title("同じ期間・同じモデルでも、起点をずらすだけで %d / %d 本の誤差率が下がる"
                 % (down, len(rows)), fontsize=13, pad=12)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    return fig


def fig_drift(m, d, lo, hi, path, keys=("YN", "YR", "CR", "W")):
    """起点からの経過年数ごとに誤差率を測る。誤差が時間で積み上がることの確認。

    起点をいくつも取って、それぞれ「起点+k年目」の絶対誤差率を集め、
    k ごとに平均する。k=0 は起点の年（ラグがすべて実績の年）。"""
    starts = [y for y in range(2000, FULL_END - 3)]
    rows = dict((v, {}) for v in keys)
    for st in starts:
        try:
            sim = simulate(m, d, st, min(st + 11, FULL_END))
        except Exception:
            continue
        for v in keys:
            for k, t in enumerate(range(st, min(st + 11, FULL_END) + 1)):
                a, s = d[v].loc[t], sim[v].loc[t]
                if np.isfinite(a) and np.isfinite(s) and abs(a) > 1e-9:
                    rows[v].setdefault(k, []).append(abs(s - a) / abs(a) * 100)

    labels = dict((v, lab) for v, lab, _u, _s in PANELS)
    # 4本を1枚に重ねると、検証済みのカテゴリ色2つでは足りず色を使い回すことに
    # なるので、小倍数にして1色で描く。縦軸は共通にして大小を比べられるようにする。
    fig, axes = plt.subplots(2, 2, figsize=(11.0, 7.0), sharex=True, sharey=True)
    for ax, v in zip(axes.ravel(), keys):
        ks = sorted(rows[v])
        ys = [float(np.mean(rows[v][k])) for k in ks]
        ax.plot(ks, ys, color=LONG, lw=2.0, marker="o", ms=5, zorder=3)
        ax.annotate("%.2f%%" % ys[0], (ks[0], ys[0]), textcoords="offset points",
                    xytext=(4, 9), fontsize=9, color=ACT)
        ax.annotate("%.2f%%" % ys[-1], (ks[-1], ys[-1]), textcoords="offset points",
                    xytext=(-4, 9), ha="right", fontsize=9, color=ACT)
        ax.set_title("%s　%.2f%% → %.2f%%（%.1f倍）"
                     % (labels.get(v, v), ys[0], ys[-1],
                        ys[-1] / ys[0] if ys[0] else float("nan")),
                     fontsize=11, pad=8)
        ax.grid(True, lw=.5, alpha=.35)
        ax.set_axisbelow(True)
        ax.set_xticks(range(0, 12, 2))
        ax.margins(y=.18)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    for ax in axes[-1]:
        ax.set_xlabel("起点からの経過年数", fontsize=10)
    for ax in axes[:, 0]:
        ax.set_ylabel("平均絶対誤差率（％）", fontsize=10)
    fig.suptitle("誤差は起点から離れるほど積み上がる　"
                 "経過0年＝ラグがすべて実績の年（%d〜%d年度の全起点で平均）"
                 % (starts[0], starts[-1]), fontsize=12.5, y=.985)
    fig.tight_layout(rect=(0, 0, 1, .955))
    fig.savefig(path, dpi=130)
    return fig


def main(argv):
    lo, hi = 2013, 2020
    if len(argv) == 2:
        lo, hi = int(argv[0]), int(argv[1])
    if not (FULL_START < lo < hi <= FULL_END):
        print("期間は %d〜%d の範囲で、起点は %d より後にしてください。"
              % (FULL_START, FULL_END, FULL_START))
        return 1

    m, d = pm.load(version=1, coeffs="reest")
    print("%d年度から通しで解いています…" % FULL_START)
    long_sim = simulate(m, d, FULL_START, FULL_END)
    print("%d年度から回し直しています…" % lo)
    short_sim = simulate(m, d, lo, hi)

    tag = "_%d_%d" % (lo, hi)
    p1 = "park_restart%s.png" % tag
    p2 = "park_restart_error%s.png" % tag
    p3 = "park_restart_drift%s.png" % tag
    f1 = fig_paths(d, long_sim, short_sim, lo, hi, p1)
    f2 = fig_error(d, long_sim, short_sim, lo, hi, p2)
    print("   %s / %s を保存" % (p1, p2))
    print("起点をずらしながら誤差の積み上がりを測っています…")
    f3 = fig_drift(m, d, lo, hi, p3)
    print("   %s を保存" % p3)

    print("\n   %d-%d年度の平均絶対誤差率" % (lo, hi))
    print("      %-20s %10s %10s %8s" % ("変数", "通し", "回し直し", "差"))
    for v, label, _u, _s in PANELS:
        a = mape(long_sim, d, v, lo, hi)
        b = mape(short_sim, d, v, lo, hi)
        print("      %-20s %9.2f%% %9.2f%% %7.2f" % (label, a, b, b - a))
    for f in (f1, f2, f3):
        plt.close(f)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
