"""abenomics_article.py -- 記事 abenomics.html を、モデルを解いた結果から作り直す。

  python abenomics_article.py

記事の本文は abenomics_template.html に入っている。本文中の数字・表・図は
{{name}} の置き場になっていて、このスクリプトが

  1. abenomics_park.run_all() で WP65 の10シナリオを解く
  2. contax_scenario.run(5) で消費税5%据え置き（論文の範囲外）を解く
  3. 記事に出る数字・5つの表・5つの図（インライン SVG）を作る
  4. 置き場に流し込んで abenomics.html に書き出す

をやる。データや係数を作り直したら、これを回せば記事の数字が全部そろう。

【文章の前提】
数字は入れ替わるが、文章は「増税しても借金が増える」「株価シナリオは半分以上が
資産の評価」のように結果の向きを前提に書いてある。向きが変わったら文章を書き
直さないといけないので、check() でその前提を確かめ、崩れていたら書き出さずに
止める。

論文の数値（WP65 表20 と、シナリオ別の累計損失）はテンプレートに直書きしてある。
モデルの数字ではなく著者の公表値なので、動かない。
"""
import datetime
import io
import os
import re
import sys

import abenomics_park as ap
import contax_scenario as cs
import parkmodel as pm

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE = os.path.join(HERE, "abenomics_template.html")
OUT = os.path.join(HERE, "abenomics.html")

BN = 1e-3                     # 十億円 → 兆円
MINUS = "−"              # 記事では負号に U+2212 を使う

# WP65 5.9節・表21 が報告するシナリオ別の累計実質GDP損失（2012-2023年度、兆円）
PAPER_CUM = {"2": -8.5, "3": 6.2, "4": -37.4, "5": -7.4, "6": -30.5, "7": -33.8, "8": -31.2}
PAPER_CUM_SUM, PAPER_CUM_ALL = -142.6, -138.5
NAMES = {"2": "利下げなし", "3": "為替が高いまま", "4": "株価が上がらない",
         "5": "2012年度の補正なし", "6": "政府消費の抑制", "7": "政府投資の抑制",
         "8": "成長戦略の効果なし"}


# ------------------------------------------------------------ 書式
def num(x, nd=1, sign=False, comma=False):
    """記事の書式。負号は U+2212、必要なら + を付ける。-0.0 は 0.0 にする。"""
    v = round(float(x), nd)
    if v == 0:
        v = 0.0
    s = ("{:,.%df}" if comma else "{:.%df}") % nd
    s = s.format(abs(v))
    if v < 0:
        return MINUS + s
    return ("+" + s) if sign else s


def n0(x, comma=False):
    return num(x, 0, comma=comma)


def cls(x):
    """表のセル色。プラスは pos、マイナスは neg。"""
    return "pos" if float(x) >= 0 else "neg"


def cls_debt(x):
    """借金の増分はプラスが悪い方向なので色を逆にする。"""
    return "neg" if float(x) >= 0 else "pos"


# ------------------------------------------------------------ 図
X0, X1 = 54.0, 600.0


def _xs(n):
    return [X0 + (X1 - X0) * i / (n - 1) for i in range(n)]


def line_chart(years, series, lo, hi, ticks, labels, ytop=18.0, ybot=290.0,
               xlabel_y=312, xlabel_years=None):
    """折れ線。series は [(class, 値のリスト)]、labels は [(class, 文字, y補正)]。"""
    xs = _xs(len(years))
    yy = lambda v: ybot - (v - lo) / (hi - lo) * (ybot - ytop)
    out = []
    for g in ticks:
        out.append('        <line class="grid" x1="54" y1="%.1f" x2="600" y2="%.1f"/>' % (yy(g), yy(g)))
        out.append('        <text class="tick" x="46" y="%.1f" text-anchor="end">%s</text>' % (yy(g) + 4, num(g, 0)))
    for i, y in enumerate(years):
        if y in (xlabel_years or ()):
            out.append('        <text class="tick" x="%.1f" y="%d" text-anchor="middle">%d</text>' % (xs[i], xlabel_y, y))
    for c, vs in series:
        assert min(vs) >= lo and max(vs) <= hi, "図の範囲外: %s %.1f-%.1f" % (c, min(vs), max(vs))
        out.append('        <path class="ln %s" d="M %s"/>' % (c, " L ".join("%.1f %.1f" % (x, yy(v)) for x, v in zip(xs, vs))))
    for c, text, dy, v in labels:
        out.append('        <text class="lbl %s" x="609.0" y="%.1f">%s</text>' % (c, yy(v) + dy, text))
    return "\n".join(out) + "\n"


def svg_yr(A, years):
    return line_chart(years, [("act", A["act"]), ("base", A["base"]), ("s10", A["s10"])],
                      500, 580, [500, 520, 540, 560, 580],
                      [("base", "ベースライン", 4, A["base"][-1]), ("s10", "なかったら", -1, A["s10"][-1]),
                       ("act", "実績", 11, A["act"][-1])],
                      xlabel_years=(2011, 2014, 2017, 2020, 2023))


def svg_ratio(R, years):
    return line_chart(years, [("act", R["act"]), ("base", R["base"]), ("s10", R["s10"])],
                      120, 280, [120, 160, 200, 240, 280],
                      [("s10", "なかったら", 4, R["s10"][-1]), ("base", "ベースライン", -1, R["base"][-1]),
                       ("act", "実績", 11, R["act"][-1])],
                      xlabel_years=(2011, 2014, 2017, 2020, 2023))


def svg_arrows(mine):
    """三本の矢。論文の値と本実装の値を横棒で並べる。x は 0 → 140、20兆円 → 126px。"""
    paper = [PAPER_CUM["2"] + PAPER_CUM["3"] + PAPER_CUM["4"],
             PAPER_CUM["5"] + PAPER_CUM["6"] + PAPER_CUM["7"], PAPER_CUM["8"]]
    k = 126.0 / 20.0
    out = []
    for i, g in enumerate((0, -20, -40, -60, -80)):
        x = 140.0 + i * 126.0
        out.append('        <line class="grid" x1="%.1f" y1="14" x2="%.1f" y2="202"/>' % (x, x))
        out.append('        <text class="tick" x="%.1f" y="220" text-anchor="middle">%s</text>' % (x, num(g, 0)))
    for i, lab in enumerate(("第一の矢　金融政策", "第二の矢　財政政策", "第三の矢　成長戦略")):
        y0 = 22.0 + i * (188.0 / 3.0)
        out.append('        <text class="cat" x="128" y="%.1f" text-anchor="end">%s</text>' % (y0 + 21.0, lab))
        for c, v, dy in (("paper", paper[i], 0.0), ("mine", mine[i], 17.0)):
            w = -v * k
            out.append('        <rect class="bar %s" x="140.0" y="%.1f" width="%.1f" height="12" rx="3"/>' % (c, y0 + dy, w))
            out.append('        <text class="val" x="%.1f" y="%.1f">%s</text>' % (140.0 + w + 7.0, y0 + dy + 10.0, num(v)))
    return "\n".join(out) + "\n"


def svg_debtbars(rows):
    """シナリオ別の純公債残高の差。x は 0 → 294.2、40兆円 → 90.8px。"""
    x0, k = 294.2, 90.8 / 40.0
    out = []
    for g in (-40, 0, 40, 80, 120, 160):
        x = x0 + g * k
        out.append('        <line class="%s" x1="%.1f" y1="14" x2="%.1f" y2="268"/>' % ("zero" if g == 0 else "grid", x, x))
        out.append('        <text class="tick" x="%.1f" y="286" text-anchor="middle">%s</text>' % (x, num(g, 0, sign=g > 0)))
    for i, (lab, v) in enumerate(rows):
        yb = 24.6 + 36.3 * i
        yt = yb + 12.0
        out.append('        <text class="cat" x="146" y="%.1f" text-anchor="end">%s</text>' % (yt, lab))
        if v >= 0:
            out.append('        <rect class="bar up" x="%.1f" y="%.1f" width="%.1f" height="15" rx="3"/>' % (x0, yb, v * k))
            out.append('        <text class="val" x="%.1f" y="%.1f" text-anchor="start">%s</text>' % (x0 + v * k + 8, yt, num(v, sign=True)))
        else:
            out.append('        <rect class="bar down" x="%.1f" y="%.1f" width="%.1f" height="15" rx="3"/>' % (x0 + v * k, yb, -v * k))
            out.append('        <text class="val" x="%.1f" y="%.1f" text-anchor="end">%s</text>' % (x0 + v * k - 8, yt, num(v)))
    return "\n".join(out) + "\n"


def svg_tax(years, d9, d5):
    """消費税2本の対GDP比の差（％ポイント）。"""
    lo, hi, ytop, ybot = -8.0, 3.0, 20.0, 268.0
    xs = _xs(len(years))
    yy = lambda v: ybot - (v - lo) / (hi - lo) * (ybot - ytop)
    out = []
    for g in (-8, -6, -4, -2, 2):
        out.append('        <line class="grid" x1="54" y1="%.1f" x2="600" y2="%.1f"/>' % (yy(g), yy(g)))
        out.append('        <text class="tick" x="46" y="%.1f" text-anchor="end">%s</text>' % (yy(g) + 4, num(g, 0, sign=True)))
    out.append('        <line class="zero" x1="54" y1="%.1f" x2="600" y2="%.1f"/>' % (yy(0), yy(0)))
    out.append('        <text class="tick" x="46" y="%.1f" text-anchor="end">0</text>' % (yy(0) + 4))
    for i, y in enumerate(years):
        if y % 3 == 2 or y == years[-1]:
            out.append('        <text class="tick" x="%.1f" y="290" text-anchor="middle">%d</text>' % (xs[i], y))
    for c, vs in (("s10", d9), ("ref", d5)):
        assert min(vs) >= lo and max(vs) <= hi, "図の範囲外: %s" % c
        out.append('        <path class="ln %s" d="M %s"/>' % (c, " L ".join("%.1f %.1f" % (x, yy(v)) for x, v in zip(xs, vs))))
    out.append('        <text class="lbl s10" x="609.0" y="%.1f">増税</text>' % (yy(d9[-1]) + 4))
    out.append('        <text class="lbl ref" x="609.0" y="%.1f">5%%据え置き</text>' % (yy(d5[-1]) + 4))
    return "\n".join(out) + "\n"


# ------------------------------------------------------------ 数字
def cum(s, b, f, y0, y1):
    return float((f(s) - f(b)).loc[y0:y1].sum() * BN)


def fiscal_parts(s, b, y0, y1):
    """政府純貸出の差を項目に割る（累計、兆円）。合計は NL_G の差にきっかり合わせる。"""
    p = {
        "tin": cum(s, b, lambda d: d["TIN_N"], y0, y1),
        "int": cum(s, b, lambda d: d["RB"].shift(1) * d["NGBA_G"].shift(1), y0, y1),
        "cb": cum(s, b, lambda d: d["FINCOME_CB"], y0, y1),
        "str": cum(s, b, lambda d: d["STR_G"], y0, y1),
        "tax": cum(s, b, lambda d: d["TD_N"] + d["T_H"] + d["T_F"], y0, y1),
        "gov": cum(s, b, lambda d: -d["GN"] - d["IN_G"], y0, y1),
        "fin": cum(s, b, lambda d: d["FINCOME_G"] - d["RB"].shift(1) * d["NGBA_G"].shift(1), y0, y1),
    }
    p["nl"] = cum(s, b, lambda d: d["NL_G"], y0, y1)
    p["other"] = p["nl"] - sum(p[k] for k in ("tin", "int", "cb", "str", "tax", "gov"))
    return p


def compute():
    runs, failed = ap.run_all(verbose=False)
    if failed:
        raise RuntimeError("解けないシナリオがある: %s" % failed)
    bl5, s5 = cs.run(5.0)
    b = runs["1. ベースライン"]
    if float((bl5["NGBA_G"] - b["NGBA_G"]).abs().max()) > 1e-6:
        raise RuntimeError("消費税のベースラインが反実仮想のベースラインと違う")
    d = pm.data()
    S, E = ap.START, ap.END
    years = list(range(S, E + 1))
    sc = {k: runs[n] for n in runs for k in [n.split(".")[0]]}   # "1".."10"
    s10, s9 = sc["10"], sc["9"]
    debt = lambda x: -x["NGBA_G"] * BN
    ratio = lambda x: -x["NGBA_G"] / x["YN"] * 100.0
    at = lambda x, k, y=E: float(x[k].loc[y])

    v = {"end": E, "nyears": E - 2013 + 1,
         "date": (datetime.datetime.utcnow() + datetime.timedelta(hours=9)).strftime("%Y年%-m月%-d日")}

    # 05 実質GDP
    v["yr_base0"] = n0(at(b, "YR") * BN)
    v["yr_s10_0"] = n0(at(s10, "YR") * BN)
    v["yr_diff0"] = n0((at(b, "YR") - at(s10, "YR")) * BN)
    v["yr_pct"] = num((1 - at(s10, "YR") / at(b, "YR")) * 100)
    cum_yr = {k: cum(sc[k], b, lambda x: x["YR"], 2012, E) for k in sc if k != "1"}
    v["cum10"] = num(-cum_yr["10"])
    A = {k: [float(x["YR"].loc[y]) * BN for y in years] for k, x in (("act", d), ("base", b), ("s10", s10))}
    v["svg:yr"] = svg_yr(A, years)

    # 06 三本の矢
    money = cum_yr["2"] + cum_yr["3"] + cum_yr["4"]
    fiscal = cum_yr["5"] + cum_yr["6"] + cum_yr["7"]
    growth = cum_yr["8"]
    v["svg:arrows"] = svg_arrows([money, fiscal, growth])
    v["fiscal0"], v["money0"] = n0(-fiscal), n0(-money)
    v["fiscal_ratio"] = num(fiscal / money)
    rows = []
    for k in "2345678":
        rows.append('    <tr><td>%s. %s</td><td class="num %s">%s</td><td class="num %s">%s</td></tr>'
                    % (k, NAMES[k], cls(PAPER_CUM[k]), num(PAPER_CUM[k], sign=True), cls(cum_yr[k]), num(cum_yr[k], sign=True)))
    ssum = sum(cum_yr[k] for k in "2345678")
    rows.append('    <tr class="total"><td>2〜8 を単純に足す</td><td class="num %s">%s</td><td class="num %s">%s</td></tr>'
                % (cls(PAPER_CUM_SUM), num(PAPER_CUM_SUM, sign=True), cls(ssum), num(ssum, sign=True)))
    rows.append('    <tr class="total"><td>2〜8 を同時にかける（全効果）</td><td class="num %s">%s</td><td class="num %s">%s</td></tr>'
                % (cls(PAPER_CUM_ALL), num(PAPER_CUM_ALL, sign=True), cls(cum_yr["10"]), num(cum_yr["10"], sign=True)))
    v["table:scen"] = "\n".join(rows)
    v["sum_cum"] = num(-ssum)
    v["s2_cum0"] = n0(cum_yr["2"])

    # 07 政府の借金
    dd = {k: float(debt(sc[k]).loc[E] - debt(b).loc[E]) for k in sc if k != "1"}
    nl = {k: -cum(sc[k], b, lambda x: x["NL_G"], 2012, E) for k in sc if k != "1"}     # 赤字の累積（プラス＝赤字が大きい）
    rv = {k: dd[k] - nl[k] for k in dd}                                              # 資産の評価
    v["debt10_0"], v["debt10"] = n0(dd["10"]), num(dd["10"])
    rb, r10 = float(ratio(b).loc[E]), float(ratio(s10).loc[E])
    v["ratio_base"], v["ratio_s10"], v["ratio_diff10"] = num(rb), num(r10), num(r10 - rb)
    R = {k: [float(ratio(x).loc[y]) for y in years] for k, x in (("act", d), ("base", b), ("s10", s10))}
    v["svg:ratio"] = svg_ratio(R, years)
    v["svg:debtbars"] = svg_debtbars([("%s. %s" % (k, NAMES[k]), dd[k]) for k in "2345678"])
    v["spend3_0"] = n0(-(dd["5"] + dd["6"] + dd["7"]))
    v["s2_debt0"], v["s4_debt0"], v["s24_debt0"] = n0(dd["2"]), n0(dd["4"]), n0(dd["2"] + dd["4"])
    rows = []
    for k in "2467":
        rows.append('    <tr><td>%s. %s</td><td class="num %s">%s</td><td class="num">%s</td><td class="num">%s</td></tr>'
                    % (k, NAMES[k], cls_debt(dd[k]), num(dd[k], sign=True), num(nl[k]), num(rv[k])))
    rows.append('    <tr class="total"><td>全効果</td><td class="num %s">%s</td><td class="num">%s</td><td class="num">%s</td></tr>'
                % (cls_debt(dd["10"]), num(dd["10"], sign=True), num(nl["10"]), num(rv["10"])))
    v["table:decomp"] = "\n".join(rows)
    p2 = fiscal_parts(sc["2"], b, 2012, E)
    v["s2_int0"], v["s2_fin0"], v["s2_tax0"], v["s2_str0"] = n0(-p2["int"]), n0(p2["fin"]), n0(p2["tax"]), n0(p2["str"])
    v["s2_cb0"] = n0(p2["cb"])
    v["debt_base0"] = n0(debt(b).loc[E], comma=True)
    v["cb_jgb0"] = n0(at(b, "NGBA_CB") * BN)
    v["gov_eq0"] = n0(at(b, "NEQUA_G") * BN)
    v["s4_reval0"] = n0(rv["4"])
    v["s10_reval"] = num(rv["10"])
    v["s4_reval_share"] = n0(rv["4"] / dd["4"] * 10)
    reval_base = float(d["NEQUACG_G"].loc[2012:E].sum() * BN)

    # 08 消費税
    d9 = float(debt(s9).loc[E] - debt(b).loc[E])
    d5 = float(debt(s5).loc[E] - debt(b).loc[E])
    n9 = -cum(s9, b, lambda x: x["NL_G"], 2012, E)
    n5 = -cum(s5, b, lambda x: x["NL_G"], 2012, E)
    v["s9_debt"], v["s5_debt_abs"] = num(d9), num(-d5)
    v["debt_base"] = num(debt(b).loc[E], comma=True)
    v["debt_s9"] = num(debt(s9).loc[E], comma=True)
    v["debt_s5"] = num(debt(s5).loc[E], comma=True)
    ty = list(range(2012, E + 1))
    r9 = [float(ratio(s9).loc[y] - ratio(b).loc[y]) for y in ty]
    r5 = [float(ratio(s5).loc[y] - ratio(b).loc[y]) for y in ty]
    v["svg:tax"] = svg_tax(ty, r9, r5)
    ipk = max(range(len(r9)), key=lambda i: r9[i])
    v["s9_peak_year"], v["s9_peak"] = ty[ipk], num(r9[ipk])
    neg = 0
    for x in reversed(r9):
        if x < 0:
            neg += 1
        else:
            break
    v["s9_neg_years"] = neg
    v["table:taxdecomp"] = "\n".join([
        '    <tr><td>9. 予定どおり増税</td><td class="num %s">%s</td><td class="num">%s</td><td class="num">%s</td></tr>'
        % (cls_debt(d9), num(d9, sign=True), num(n9), num(d9 - n9)),
        '    <tr><td>5%%のまま据え置き<span style="color:var(--ink-3)">（拡張）</span></td><td class="num %s">%s</td><td class="num">%s</td><td class="num">%s</td></tr>'
        % (cls_debt(d5), num(d5, sign=True), num(n5), num(d5 - n5)),
        '    <tr><td style="color:var(--ink-3)">参考：4. %s</td><td class="num %s">%s</td><td class="num">%s</td><td class="num">%s</td></tr>'
        % (NAMES["4"], cls_debt(dd["4"]), num(dd["4"], sign=True), num(nl["4"]), num(rv["4"]))])
    p9, p5 = fiscal_parts(s9, b, 2012, E), fiscal_parts(s5, b, 2012, E)
    flow_rows = [("消費税ほか純間接税", "tin"), ("国債の利子の支払い", "int"),
                 ("日銀からの納付金（日銀が受け取った利子が戻る）", "cb"), ("社会保障の収支", "str"),
                 ("所得税・法人税など", "tax"), ("政府消費・政府投資（名目）", "gov"),
                 ("その他（営業余剰・財産所得ほか）", "other")]
    rows = ['    <tr><td>%s</td><td class="num %s">%s</td><td class="num %s">%s</td></tr>'
            % (lab, cls(p9[k]), num(p9[k], sign=True), cls(p5[k]), num(p5[k], sign=True)) for lab, k in flow_rows]
    rows.append('    <tr class="total"><td>合計＝財政収支の累計差</td><td class="num %s">%s</td><td class="num %s">%s</td></tr>'
                % (cls(p9["nl"]), num(p9["nl"], sign=True), cls(p5["nl"]), num(p5["nl"], sign=True)))
    v["table:taxflow"] = "\n".join(rows)
    v["s9_tin"], v["s9_int_abs"], v["s9_cb"] = num(p9["tin"]), num(-p9["int"]), num(p9["cb"])
    v["s9_int_net"] = num(-(p9["int"] + p9["cb"]))
    v["s9_str_abs"], v["s9_tax_abs"] = num(-p9["str"]), num(-p9["tax"])
    v["s5_tin_abs"], v["s5_int"], v["s5_cb_abs"] = num(-p5["tin"]), num(p5["int"]), num(-p5["cb"])
    v["s5_int_net"] = num(p5["int"] + p5["cb"])
    v["s5_strtax"], v["s5_gov_abs"], v["s5_nl"] = num(p5["str"] + p5["tax"]), num(-p5["gov"]), num(p5["nl"])
    rows = []
    for lab, x in (("ベースライン", b), ("9. 予定どおり増税", s9), ("5%のまま据え置き", s5)):
        rows.append('    <tr><td>%s</td><td class="num">%s</td><td class="num">%s%%</td><td class="num">%s</td><td class="num">%s</td></tr>'
                    % (lab, num(debt(x).loc[E], comma=True), num(ratio(x).loc[E]), num(at(x, "YN") * BN), num(at(x, "YR") * BN)))
    v["table:taxlevels"] = "\n".join(rows)
    pct = lambda x, k: (at(x, k) / at(b, k) - 1) * 100
    v["s9_yn_pct"], v["s9_yr_pct_abs"] = num(pct(s9, "YN")), num(-pct(s9, "YR"))
    v["s9_ratio_abs"] = num(rb - float(ratio(s9).loc[E]))
    v["s5_yn_pct"], v["s5_yr_pct"] = num(pct(s5, "YN")), num(pct(s5, "YR"))
    v["s5_ratio_abs"] = num(rb - float(ratio(s5).loc[E]))
    v["s5_unr_min"] = num(s5["UNR"].loc[S:E].min(), 2)
    v["unr_data_min"] = num(d["UNR"].loc[1994:E].min(), 2)

    # 09 論文 表20 との突き合わせ
    rows = []
    gaps = {}
    for k, lab in (("YR", "実質GDP"), ("YN", "名目GDP"), ("IR_N", "実質設備投資"), ("W", "名目賃金率"), ("CR", "実質家計消費")):
        paper = [ap.PAPER_S10[k][y] for y in ap.REPORT]
        mine = [(float(s10[k].loc[y]) / float(b[k].loc[y]) - 1) * 100 for y in ap.REPORT]
        gaps[k] = [round(m, 1) - p for p, m in zip(paper, mine)]
        rows.append('    <tr><td rowspan="2">%s</td><td>論文</td>%s</tr>' % (lab, "".join('<td class="num">%s</td>' % num(p) for p in paper)))
        rows.append('    <tr><td>再実装</td>%s</tr>' % "".join('<td class="num">%s</td>' % num(m, sign=m > 0) for m in mine))
    v["table:t20"] = "\n".join(rows)
    v["yr_maxgap"] = num(max(abs(g) for g in gaps["YR"]))
    ynw = gaps["YN"] + gaps["W"]
    v["ynw_gap_lo"], v["ynw_gap_hi"] = num(min(ynw)), num(max(ynw))
    v["cum_pct_diff"] = n0(abs(-cum_yr["10"] - 138.5) / 138.5 * 100)

    facts = dict(d9=d9, d5=d5, r9=r9, r5=r5, cum2=cum_yr["2"], dd=dd, rv=rv, reval_base=reval_base,
                 yn10=pct(s10, "YN"), cb2=p2["cb"], ynw=ynw, gaps_yr=gaps["YR"])
    return v, facts


def check(f):
    """文章が前提にしている結果の向き。崩れていたら文章を書き直す必要がある。"""
    tests = [
        ("増税すると借金が増える（08 の見出しと本文）", f["d9"] > 0),
        ("5%据え置きで借金が減る（08）", f["d5"] < 0),
        ("増税・据え置きとも対GDP比は下がる（08「どちらも下がる」）", f["r9"][-1] < 0 and f["r5"][-1] < 0),
        ("増税の対GDP比は途中で悪化してから下がる（08 図のキャプション）", max(f["r9"]) > 0),
        ("利下げなしで実質GDPの累計がプラス（06「利下げで実質GDPが下がる？」）", f["cum2"] > 0),
        ("歳出を絞る3本は借金を減らす（07）", all(f["dd"][k] < 0 for k in "567")),
        ("利下げなしと株価は借金を増やし、他より大きい（07）",
         f["dd"]["2"] > 0 and f["dd"]["4"] > 0 and min(f["dd"]["2"], f["dd"]["4"]) > max(abs(f["dd"][k]) for k in "35678")),
        ("株価シナリオは半分以上が資産の評価（07・08）", f["rv"]["4"] / f["dd"]["4"] > 0.5),
        ("利下げなしの資産の評価はほぼゼロ（07「まるごと利払い」）", abs(f["rv"]["2"]) < 1.0),
        ("全効果の資産の評価が政府保有株の評価益の累計と一致（07 note）", abs(f["rv"]["10"] - f["reval_base"]) < 0.1),
        ("利下げなしで日銀の納付金がほとんど動かない（07 note）", abs(f["cb2"]) < 10.0),
        ("なかったら世界の名目GDPは1割ほど低い（07「2つの読み方」）", -15.0 < f["yn10"] < -5.0),
        ("名目GDPと賃金は論文より深くは出ない（09）", min(f["ynw"]) >= -0.05),
        ("実質GDPは論文と1%pt以内（09）", max(abs(g) for g in f["gaps_yr"]) <= 1.0),
    ]
    bad = [name for name, ok in tests if not ok]
    for name, ok in tests:
        print("   %s %s" % ("OK" if ok else "NG", name))
    return bad


def render(v):
    t = io.open(TEMPLATE, encoding="utf-8").read()
    for k, x in v.items():
        t = t.replace("{{%s}}" % k, str(x).rstrip("\n"))
    left = sorted(set(re.findall(r"\{\{[^}]+\}\}", t)))
    if left:
        raise ValueError("埋まらなかった置き場: %s" % ", ".join(left))
    return t


def main():
    print("=" * 78)
    print("記事 abenomics.html を作り直す")
    print("=" * 78)
    if not ap.check_equations():
        print("方程式が論文から変わっているので、ここで止める。")
        return 1
    print("\n10シナリオと消費税5%据え置きを解いています…")
    v, facts = compute()
    print("\n文章の前提を確かめる")
    bad = check(facts)
    if bad:
        print("\n結果の向きが文章の前提と違う。abenomics_template.html の文章を書き直すこと:")
        for name in bad:
            print("   - %s" % name)
        return 1
    html = render(v)
    io.open(OUT, "w", encoding="utf-8").write(html)
    print("\n   %s に書き出した（%d 文字）" % (os.path.basename(OUT), len(html)))
    print("   全効果の累計損失 %s 兆円 / 純公債残高 +%s 兆円 / 増税 +%s 兆円 / 5%%据え置き −%s 兆円"
          % (v["cum10"], v["debt10"], v["s9_debt"], v["s5_debt_abs"]))
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())
