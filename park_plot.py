"""park_plot.py -- ファイナルテストの結果を図にする。

  python park_plot.py              1997年度からデータの最終年度まで
  python park_plot.py 2013 2020    その期間だけを切り出す

【重要】期間を指定しても、シミュレーションは必ず 1997年度から通しで走らせる。
表示する窓を切るだけである。2013年度から解き直すと、初期値に実績を与える年が
2013年度になり、誤差が積み上がる年数が減って別物の（楽な）テストになる。

出力:
  park_final.png        主要12変数の実績とモデルの推移
  park_final_error.png  論文 表12 との誤差率の比較
  期間を指定したときは park_final_2013_2020.png のように接尾辞が付く
"""
import base64
import io as _io
import os
import re
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from jfont import use_japanese_font
import parkmodel as pm

use_japanese_font()

ACT = "#1a1a19"      # 実績。テキスト色に近い中立色
MOD = "#2a78d6"      # モデル。検証済みの categorical slot 1
REF = "#eb6834"      # 論文。同 slot 2

START, END = 1997, pm.last_year()   # 動学シミュレーションの区間。ここは動かさない

# (変数, 見出し, 単位, 表示倍率)
PANELS = [
    ("YN",    "名目GDP",        "兆円", 1e-3),
    ("YR",    "実質GDP",        "兆円", 1e-3),
    ("CR",    "実質家計消費",    "兆円", 1e-3),
    ("IR_N",  "実質法人投資",    "兆円", 1e-3),
    ("XR",    "実質輸出",        "兆円", 1e-3),
    ("MR",    "実質輸入",        "兆円", 1e-3),
    ("PC",    "消費デフレータ",  None, 1.0),      # 単位はデータの基準年から作る
    ("W",     "名目賃金率",      "十万円/人", 1.0),
    ("N_N",   "就業者数",        "万人", 1.0),
    ("UNR",   "失業率",          "％", 1.0),
    ("TIN_N", "純間接税",        "兆円", 1e-3),
    ("KN_N",  "法人の資本ストック", "兆円", 1e-3),
]


def mape(sim, act, v, start, end):
    a = act[v].loc[start:end]
    s = sim[v].loc[start:end]
    ok = np.isfinite(a) & np.isfinite(s) & (a.abs() > 1e-9)
    return float(((s[ok] - a[ok]).abs() / a[ok].abs() * 100).mean())


def fig_paths(m, d, sim, lo, hi, path):
    fig, axes = plt.subplots(4, 3, figsize=(13.5, 13.0))
    yrs = list(range(lo, hi + 1))
    base = "%d年度=1" % pm.deflator_base()     # 確報の版で変わる
    for ax, (v, label, unit, scale) in zip(axes.ravel(), PANELS):
        unit = base if unit is None else unit
        a = d[v].loc[lo:hi] * scale
        s = sim[v].loc[lo:hi] * scale
        ax.plot(yrs, a.values, color=ACT, lw=2.0, label="実績", zorder=3)
        ax.plot(yrs, s.values, color=MOD, lw=2.0, ls="--", label="モデル", zorder=2)
        ax.set_title("%s（%s）　誤差率 %.2f%%" % (label, unit, mape(sim, d, v, lo, hi)),
                     fontsize=11, pad=8)
        ax.grid(True, lw=.5, alpha=.35)
        ax.tick_params(labelsize=9)
        ax.set_xlim(lo, hi)
        if hi - lo <= 12:
            ax.set_xticks(range(lo, hi + 1, 1 if hi - lo <= 8 else 2))
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    axes.ravel()[0].legend(loc="upper left", fontsize=9, frameon=False)
    fig.suptitle("ファイナルテスト %d–%d年度　%d年度の初期値だけ実績を与え、"
                 "そこから%d年間モデルに解かせた結果（誤差率は表示期間のもの）"
                 % (lo, hi, START, END - START + 1), fontsize=13, y=.995)
    fig.tight_layout(rect=(0, 0, 1, .985))
    fig.savefig(path, dpi=130)
    return fig


def fig_error(sim, d, lo, hi, path):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper"))
    from paper_table12 import PAPER_T12
    names = {"YN": "名目GDP", "W": "名目賃金", "TIN_N": "純間接税", "PC": "消費デフレータ",
             "CR": "実質家計消費", "N_N": "就業者数", "B2": "営業余剰", "XR": "実質輸出",
             "MR": "実質輸入", "TD_N": "直接税", "T_H": "家計の直接税", "PY": "GDPデフレータ",
             "Y_H": "家計の総所得", "YD_H": "家計可処分所得", "KN_N": "法人の資本ストック",
             "S_N": "法人貯蓄", "UNR": "失業率"}
    rows = [(names[v], PAPER_T12[v], mape(sim, d, v, lo, hi))
            for v in names if v in PAPER_T12 and v in sim.columns]
    rows.sort(key=lambda r: r[1])
    lab = [r[0] for r in rows]
    y = np.arange(len(rows))
    h = 0.38
    fig, ax = plt.subplots(figsize=(9.5, 7.2))
    ax.barh(y + h / 2, [r[1] for r in rows], height=h, color=REF, label="論文（1997–2023年度）")
    ax.barh(y - h / 2, [r[2] for r in rows], height=h, color=MOD,
            label="本実装（%d–%d年度）" % (lo, hi))
    for i, r in enumerate(rows):
        ax.text(r[1] + .5, i + h / 2, "%.1f" % r[1], va="center", fontsize=8.5, color=ACT)
        ax.text(r[2] + .5, i - h / 2, "%.1f" % r[2], va="center", fontsize=8.5, color=ACT)
    ax.set_yticks(y, lab, fontsize=10)
    ax.set_xlabel("平均絶対誤差率（％、小さいほど実績に近い）", fontsize=10)
    ax.set_xlim(0, max(max(r[1], r[2]) for r in rows) * 1.16)
    ax.grid(True, axis="x", lw=.5, alpha=.35)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.legend(loc="lower right", fontsize=10, frameon=False)
    ax.set_title("ファイナルテストの誤差率　論文 表12 との比較", fontsize=13, pad=12)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    return fig


def embed_into_guide(figs, path="guide.html"):
    """guide.html の <img data-fig="..."> に png を埋め込む。

    アーティファクトとして公開したページは外部の画像を読み込めないので、
    data URI にして HTML の中に入れてしまう。"""
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
            raise ValueError("guide.html の data-fig=\"%s\" が %d 個" % (key, n))
    _io.open(path, "w", encoding="utf-8").write(html)
    return path


def main(argv):
    lo, hi = START, END
    if len(argv) == 2:
        lo, hi = int(argv[0]), int(argv[1])
        if not (START <= lo < hi <= END):
            print("期間は %d〜%d の範囲で指定してください。" % (START, END))
            return 1
    whole = (lo, hi) == (START, END)
    tag = "" if whole else "_%d_%d" % (lo, hi)

    print("ファイナルテストを %d-%d年度で解いています…" % (START, END))
    m, d = pm.load(version=1, coeffs="reest")
    sim = m.simulate(d, START, END, mode="dynamic", maxit=5000, tol=1e-7)
    p1 = "park_final%s.png" % tag
    p2 = "park_final_error%s.png" % tag
    f1 = fig_paths(m, d, sim, lo, hi, p1)
    f2 = fig_error(sim, d, lo, hi, p2)
    print("   %s / %s を保存（表示期間 %d-%d年度）" % (p1, p2, lo, hi))
    if whole:
        g = embed_into_guide({"final": f1, "error": f2})
        if g:
            print("  ", g, "にも埋め込んだ")
    plt.close(f1)
    plt.close(f2)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
