"""forecast_plot.py -- 前向きシミュレーションを図にする。

  python forecast_plot.py [年数]      既定は10年（データの最終年度の翌年から）

【この図は予測ではない】
外生変数の将来値はこちらが置いた想定であり、朴(2025c)(2026) の範囲外である。
著者は「難しい将来の外生変数の想定を避け」て前向きシミュレーションを行って
いない。想定の中身は forecast.py の docstring を見ること。

出力:
  forecast_<開始>_<終了>.png    主要12変数。実績と前向きを1本の線でつなぐ
  forecast_assumptions_<開始>_<終了>.png  想定の置き方で結果がどれだけ変わるか
"""
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from jfont import use_japanese_font
import forecast as fc
import parkmodel as pm

use_japanese_font()

# 消費デフレータの基準年。確報の版で変わるのでデータから作る
# （2023年度確報は2015年度、2024年度確報は2020年度）。
_PC_BASE = "%d年度=1" % pm.deflator_base()

ACT = "#1a1a19"      # 実績。基準として置くインク色（カテゴリ色ではない）
MOD = "#2a78d6"      # 前向き。検証済みの categorical slot 1
ALT = "#eb6834"      # 比べる想定。同 slot 2

HIST_FROM = 2010     # 図の左端。前向きとの対比が見える程度に遡る

# (変数, 見出し, 単位, 表示倍率)。None なら比率として別に計算する
PANELS = [
    ("YN",    "名目GDP",        "兆円", 1e-3),
    ("YR",    "実質GDP",        "兆円", 1e-3),
    ("PC",    "消費デフレータ",  _PC_BASE, 1.0),
    ("W",     "名目賃金率",      "十万円/人", 1.0),
    ("N_N",   "就業者数",        "万人", 1.0),
    ("UNR",   "失業率",          "％", 1.0),
    ("CR",    "実質家計消費",    "兆円", 1e-3),
    ("IR_N",  "実質法人投資",    "兆円", 1e-3),
    ("KN_N",  "法人の資本ストック", "兆円", 1e-3),
    ("MS",    "マネーストック",  "兆円", 1e-3),
    ("NGB_GDP", "純公債残高対GDP比", "％", None),
    ("NL_GDP",  "政府純貸出対GDP比", "％", None),
]


def series(sim, key, scale):
    if scale is not None:
        return sim[key] * scale
    if key == "NGB_GDP":
        return -sim["NGBA_G"] / sim["YN"] * 100.0
    if key == "NL_GDP":
        return sim["NL_G"] / sim["YN"] * 100.0
    raise KeyError(key)


def _style(ax, lo, hi, split):
    ax.axvspan(split + .5, hi, color=MOD, alpha=.055, lw=0, zorder=0)
    ax.grid(True, lw=.5, alpha=.35)
    ax.set_axisbelow(True)
    ax.set_xlim(lo, hi)
    ax.set_xticks(range(lo, hi + 1, 5 if hi - lo > 18 else 4))
    ax.tick_params(labelsize=9)
    ax.margins(y=.14)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def fig_paths(sim, horizon, path):
    """実績と前向きを1本の線で描き、前向きの区間に薄い網をかける。"""
    lo, split, hi = HIST_FROM, fc.LAST, fc.LAST + horizon
    yrs = list(range(lo, hi + 1))
    fig, axes = plt.subplots(4, 3, figsize=(13.5, 13.4))
    for ax, (k, label, unit, scale) in zip(axes.ravel(), PANELS):
        s = series(sim, k, scale).loc[lo:hi]
        ax.plot(yrs[:split - lo + 1], s.loc[lo:split].values, color=ACT, lw=2.0,
                label="実績にもとづく期間", zorder=3)
        ax.plot(yrs[split - lo:], s.loc[split:hi].values, color=MOD, lw=2.0,
                ls="--", label="前向き（想定にもとづく）", zorder=3)
        ax.set_title("%s（%s）\n%d年度 %.1f → %d年度 %.1f"
                     % (label, unit, split, s.loc[split], hi, s.loc[hi]),
                     fontsize=10.5, pad=8)
        _style(ax, lo, hi, split)
    h, l = axes.ravel()[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", bbox_to_anchor=(.5, .952), ncol=2,
               fontsize=10, frameon=False)
    fig.suptitle("前向きシミュレーション %d–%d年度　"
                 "これは予測ではなく、置いた想定のもとでモデルが出す経路である"
                 % (split + 1, hi), fontsize=13, y=.988)
    fig.tight_layout(rect=(0, 0, 1, .944))
    fig.savefig(path, dpi=130)
    return fig


def fig_assumptions(runs, horizon, path):
    """想定を変えると結果がどれだけ動くかを見る。"""
    lo, split, hi = HIST_FROM, fc.LAST, fc.LAST + horizon
    yrs = list(range(lo, hi + 1))
    keys = [("YR", "実質GDP", "兆円", 1e-3), ("N_N", "就業者数", "万人", 1.0),
            ("PC", "消費デフレータ", _PC_BASE, 1.0),
            ("NGB_GDP", "純公債残高対GDP比", "％", None)]
    (base_lab, base), (alt_lab, alt) = runs
    fig, axes = plt.subplots(1, 4, figsize=(13.5, 4.0))
    for ax, (k, label, unit, scale) in zip(axes, keys):
        a = series(base, k, scale).loc[lo:hi]
        b = series(alt, k, scale).loc[lo:hi]
        ax.plot(yrs, a.values, color=MOD, lw=2.0, ls="--", label=base_lab, zorder=3)
        ax.plot(yrs, b.values, color=ALT, lw=2.0, ls=":", label=alt_lab, zorder=2)
        ax.plot(yrs[:split - lo + 1], a.loc[lo:split].values, color=ACT, lw=2.0,
                label="実績にもとづく期間", zorder=4)
        ax.set_title("%s（%s）\n%d年度で %.1f と %.1f"
                     % (label, unit, hi, a.loc[hi], b.loc[hi]), fontsize=10, pad=8)
        _style(ax, lo, hi, split)
    h, l = axes[0].get_legend_handles_labels()
    fig.legend(h, l, loc="upper center", bbox_to_anchor=(.5, .93), ncol=3,
               fontsize=9.5, frameon=False)
    fig.suptitle("想定を変えると結果はどれだけ動くか", fontsize=12.5, y=.995)
    fig.tight_layout(rect=(0, 0, 1, .84))
    fig.savefig(path, dpi=130)
    return fig


def embed_into_guide(figs, path="guide.html"):
    """guide.html の <img data-fig="..."> に png を埋め込む。

    park_plot.py と同じ仕組み。公開ページは外部の画像を読めないので、
    data URI にして HTML の中に入れてしまう。"""
    import base64
    import io as _io
    import os
    import re
    if not os.path.exists(path):
        return None
    html = _io.open(path, encoding="utf-8").read()
    for key, fig in figs.items():
        buf = _io.BytesIO()
        fig.savefig(buf, format="png", dpi=100)       # 埋め込み用は少し軽く
        uri = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        pat = re.compile(r'(<img data-fig="%s"[^>]*?src=")[^"]*(")' % key)
        html, n = pat.subn(lambda m: m.group(1) + uri + m.group(2), html)
        if n != 1:
            raise ValueError('guide.html の data-fig="%s" が %d 個' % (key, n))
    _io.open(path, "w", encoding="utf-8").write(html)
    return path


def main(argv):
    horizon = int(argv[0]) if argv else 10
    end = fc.LAST + horizon
    print("=" * 78)
    print("前向きシミュレーションの図（%d-%d年度）" % (fc.LAST + 1, end))
    print("=" * 78)

    print("\n[本線] 名目フローは対GDP比据え置き、労働力人口は社人研の推計")
    m, d, _ = fc.load(horizon=horizon, nominal="gdp")
    sim = m.simulate(d, 1997, end, mode="dynamic", maxit=5000, tol=1e-7)

    print("[比較] 名目フローも労働力人口も%d年度で据え置き" % fc.LAST)
    m2, d2, _ = fc.load(horizon=horizon, nominal="hold",
                        overrides={"LF": float(d["LF"].loc[fc.LAST])})
    sim2 = m2.simulate(d2, 1997, end, mode="dynamic", maxit=5000, tol=1e-7)

    tag = "_%d_%d" % (fc.LAST + 1, end)
    p1, p2 = "forecast%s.png" % tag, "forecast_assumptions%s.png" % tag
    f1 = fig_paths(sim, horizon, p1)
    f2 = fig_assumptions([("人口減を織り込む", sim), ("すべて据え置き", sim2)],
                         horizon, p2)
    print("\n   %s / %s を保存" % (p1, p2))
    if horizon == 10:                    # ガイドに載せるのは既定の10年のときだけ
        g = embed_into_guide({"forecast": f1})
        if g:
            print("   %s にも埋め込んだ" % g)

    print("\n   %d年度の値の比較" % end)
    print("   %-22s %14s %14s" % ("", "人口減を織り込む", "すべて据え置き"))
    for k, label, unit, scale in PANELS:
        a = series(sim, k, scale).loc[end]
        b = series(sim2, k, scale).loc[end]
        print("   %-22s %14.1f %14.1f" % ("%s[%s]" % (label, unit), a, b))
    print("\n   ※ どちらも予測ではない。置いた想定のもとでモデルが出す経路である。")
    plt.close(f1)
    plt.close(f2)
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
