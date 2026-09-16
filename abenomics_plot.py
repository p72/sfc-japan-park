"""abenomics_plot.py -- WP65 の反実仮想を図にする。

  python abenomics_plot.py              2013年度〜データの最終年度
  python abenomics_plot.py 2013 2020    その期間だけを切り出す

シミュレーションは abenomics_park.run_all() がやる。区間は abenomics_park の
START〜END（2010年度〜データの最終年度）で固定で、期間指定は表示する窓を切るだけである。

読み方
  ベースライン       アベノミクスが「実際にあった」世界。外生変数は全部実績
  シナリオ           その一部を「なかったこと」にした世界
  グラフの値         シナリオ ÷ ベースライン − 1（％）。マイナスなら
                     「アベノミクスが無ければその分低かった」＝政策に効果があった

出力:
  abenomics_paths.png       主要変数のベースライン比の推移（論文 表20 と重ねる）
  abenomics_scenarios.png   シナリオ別の実質GDPへの効果
"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from jfont import use_japanese_font
import abenomics_park as ab

use_japanese_font()

ACT = "#1a1a19"      # 目盛り・注記。テキスト色に近い中立色
MOD = "#2a78d6"      # 本実装。検証済みの categorical slot 1
REF = "#eb6834"      # 論文。同 slot 2

BASE = "1. ベースライン"
S10 = "10. アベノミクス全効果"

# (変数, 見出し, 差でみるか)
PANELS = [("YN", "名目GDP", False), ("YR", "実質GDP", False),
          ("IR_N", "実質法人投資", False), ("CR", "実質家計消費", False),
          ("W", "名目賃金率", False), ("PC", "消費デフレータ", True)]


def paper_value(v, y, diff):
    src = ab.PAPER_S10_DIFF if diff else ab.PAPER_S10
    return src.get(v, {}).get(y)


def fig_paths(runs, lo, hi, path):
    bl, r = runs[BASE], runs[S10]
    yrs = list(range(lo, hi + 1))
    fig, axes = plt.subplots(2, 3, figsize=(13.5, 7.6))
    for ax, (v, label, diff) in zip(axes.ravel(), PANELS):
        if diff:
            mine = (r[v] - bl[v]).loc[lo:hi]
            unit = "ベースラインとの差"
        else:
            mine = ((r[v] / bl[v] - 1) * 100).loc[lo:hi]
            unit = "ベースライン比 ％"
        ax.axhline(0, color=ACT, lw=1.0, zorder=1)
        ax.plot(yrs, mine.values, color=MOD, lw=2.0, label="本実装", zorder=3)
        px = [(y, paper_value(v, y, diff)) for y in yrs]
        px = [(y, p) for y, p in px if p is not None]
        if px:
            ax.plot([y for y, _ in px], [p for _, p in px], "o", ms=8,
                    color=REF, label="論文 表20", zorder=4)
        ax.set_title("%s（%s）" % (label, unit), fontsize=11, pad=8)
        ax.grid(True, lw=.5, alpha=.35)
        ax.set_axisbelow(True)
        ax.set_xlim(lo, hi)
        ax.set_xticks(range(lo, hi + 1, 1 if hi - lo <= 8 else 2))
        ax.tick_params(labelsize=9)
        ax.margins(y=.14)          # 論文の点が枠にかからないよう上下に余白をとる
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    h, l = axes.ravel()[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", bbox_to_anchor=(.5, .945), ncol=2,
               fontsize=10, frameon=False)
    fig.suptitle("アベノミクスが無かった場合（シナリオ10）　%d–%d年度　"
                 "マイナスは「無ければその分低かった」＝政策に効果があったことを意味する"
                 % (lo, hi), fontsize=12.5, y=.99)
    fig.tight_layout(rect=(0, 0, 1, .925))
    fig.savefig(path, dpi=130)
    return fig


def fig_scenarios(runs, lo, hi, path):
    """シナリオ別に、実質GDPがベースラインからどれだけ離れるか。"""
    bl = runs[BASE]
    rows = []
    for name in runs:
        if name == BASE:
            continue
        d = ((runs[name]["YR"] / bl["YR"] - 1) * 100).loc[lo:hi]
        rows.append((name, float(d.loc[hi]), float(d.mean())))
    rows.sort(key=lambda t: t[2])
    lab = [t[0] for t in rows]
    y = np.arange(len(rows))
    h = 0.38

    fig, ax = plt.subplots(figsize=(10.5, 6.4))
    ax.barh(y + h / 2, [t[2] for t in rows], height=h, color=MOD,
            label="%d–%d年度の平均" % (lo, hi))
    ax.barh(y - h / 2, [t[1] for t in rows], height=h, color=REF,
            label="%d年度" % hi)
    for i, t in enumerate(rows):
        for val, off in ((t[2], h / 2), (t[1], -h / 2)):
            ax.text(val - .12 if val < 0 else val + .12, i + off, "%.1f" % val,
                    va="center", ha="right" if val < 0 else "left",
                    fontsize=8.5, color=ACT)
    ax.axvline(0, color=ACT, lw=1.0)
    ax.set_yticks(y, lab, fontsize=10)
    ax.set_xlabel("実質GDPのベースライン比（％）", fontsize=10)
    lim = max(abs(v) for t in rows for v in (t[1], t[2])) * 1.28
    ax.set_xlim(-lim, lim * .35)
    ax.grid(True, axis="x", lw=.5, alpha=.35)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    # 凡例は右下へ。左下は「10. アベノミクス全効果」の棒とラベルで埋まっている
    ax.legend(loc="lower right", fontsize=10, frameon=False)
    ax.set_title("どの政策が効いたか　シナリオ別の実質GDPへの影響", fontsize=13, pad=12)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    return fig


def main(argv):
    lo, hi = 2013, ab.END
    if len(argv) == 2:
        lo, hi = int(argv[0]), int(argv[1])
        if not (2012 <= lo < hi <= ab.END):
            print("期間は 2012〜%d の範囲で指定してください。" % ab.END)
            return 1
    print("=" * 78)
    print("反実仮想を解いています（%d-%d年度、表示は %d-%d年度）"
          % (ab.START, ab.END, lo, hi))
    print("=" * 78)
    runs, failed = ab.run_all()
    for name in (BASE, S10):
        if name not in runs:
            print("%s が解けないので図にできない。" % name)
            return 1

    tag = "_%d_%d" % (lo, hi)
    p1, p2 = "abenomics_paths%s.png" % tag, "abenomics_scenarios%s.png" % tag
    f1 = fig_paths(runs, lo, hi, p1)
    f2 = fig_scenarios(runs, lo, hi, p2)
    print("\n   %s / %s を保存" % (p1, p2))

    bl, r = runs[BASE], runs[S10]
    loss = float((bl["YR"] - r["YR"]).loc[lo:hi].sum()) / 1000.0
    print("   %d-%d年度の累計実質GDP損失 %.1f 兆円" % (lo, hi, loss))
    plt.close(f1)
    plt.close(f2)
    print("=" * 78)
    if failed:
        print("解けなかったシナリオが %d 本ある。図は解けたぶんだけ" % len(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
