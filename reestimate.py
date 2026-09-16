"""reestimate.py -- 論文の推定式の係数を、こちらのデータで推定し直す。

朴(2025c) の方程式体系169本のうち35本は、著者が EViews で推定した行動方程式
である。係数は著者が組んだデータセットの上で推定されたものなので、こちらの
データ（手元の確報）にそのまま移せない。詳しくは
paper/plan_a_original_coefficients.md を参照。

ここでは式の形は原文のまま使い、係数だけ推定し直す。出力は
paper/park2025c_model_reest.eq で、原文と同じ並び・同じ変数名のまま、
係数の数値だけが置き換わったものになる。

推定式の見分け方は、小数点以下6桁以上の数値を含むかどうか。EViews の
出力をそのまま貼り付けているので、定義式の係数（1 や 0.75 など）とは
桁数がはっきり違う。
"""
import os
import re
import sys

import numpy as np
import pandas as pd

from sfcsim import ols

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "paper", "park2025c_model.eq")
DST = os.path.join(HERE, "paper", "park2025c_model_reest.eq")
DST_WP65 = os.path.join(HERE, "paper", "park2026wp65_model_reest.eq")

_NUM = re.compile(r"\d+\.\d+")
_TERM_HEAD = re.compile(r"^([0-9]+(?:\.[0-9]+)?(?:e[+-]?[0-9]+)?)\s*(?:\*\s*(.+))?$", re.I)


def is_estimated(line):
    """EViews の推定出力をそのまま貼った式か。"""
    return any(len(m.split(".")[1]) >= 6 for m in _NUM.findall(line))


def split_terms(rhs):
    """右辺を、括弧の外側の + と - で項に分ける。符号つきで返す。"""
    terms, depth, cur, sign = [], 0, "", 1
    i = 0
    while i < len(rhs):
        c = rhs[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if depth == 0 and c in "+-" and cur.strip():
            # 指数表記の途中（1e+7 の +）は項の切れ目ではない
            if not re.search(r"[0-9]e$", cur.strip(), re.I):
                terms.append((sign, cur.strip()))
                sign = 1 if c == "+" else -1
                cur = ""
                i += 1
                continue
        if depth == 0 and c in "+-" and not cur.strip():
            sign = sign * (1 if c == "+" else -1)
            i += 1
            continue
        cur += c
        i += 1
    if cur.strip():
        terms.append((sign, cur.strip()))
    return terms


def parse(line):
    """推定式を (被説明変数の式, [説明変数の式], 定数項の有無) に分解する。

    論文には次の4つの形が出てくる。いずれも被説明変数を作り直せば
    ふつうの線形回帰になる。

      LOG(X) = ...          そのまま。被説明変数は LOG(X)
      X / Z  = ...          そのまま。被説明変数は X / Z
      X = Z * ( ... )       両辺を Z で割る。被説明変数は X / Z
      X = ( ... ) * Z       同上
    """
    lhs, rhs = line.split("=", 1)
    lhs, rhs = lhs.strip(), rhs.strip()
    dep = lhs
    m = re.match(r"^([A-Za-z_]\w*(?:\(-?\d+\))?)\s*\*\s*\((.+)\)\s*$", rhs)
    if m and lhs.count("/") == 0:
        dep = "%s / (%s)" % (lhs, m.group(1))
        rhs = m.group(2)
    else:
        m = re.match(r"^\((.+)\)\s*\*\s*([A-Za-z_]\w*(?:\(-?\d+\))?)\s*$", rhs)
        if m and lhs.count("/") == 0:
            dep = "%s / (%s)" % (lhs, m.group(2))
            rhs = m.group(1)
    xs, const = [], False
    for sign, t in split_terms(rhs):
        mm = _TERM_HEAD.match(t)
        if not mm:
            raise ValueError("項を解釈できません: %r （式 %r）" % (t, line))
        if mm.group(2) is None:
            const = True
        else:
            xs.append(mm.group(2).strip())
    return dep, xs, const


def fmt(x):
    return ("%.12g" % x)


def rebuild(line, coef, const):
    """推定し直した係数で式を組み立て直す。並びと変数名は原文のまま。"""
    lhs, rhs = line.split("=", 1)
    lhs, rhs = lhs.strip(), rhs.strip()
    scale = None
    m = re.match(r"^([A-Za-z_]\w*(?:\(-?\d+\))?)\s*\*\s*\((.+)\)\s*$", rhs)
    if m and lhs.count("/") == 0:
        scale, rhs, pre = m.group(1), m.group(2), True
    else:
        m = re.match(r"^\((.+)\)\s*\*\s*([A-Za-z_]\w*(?:\(-?\d+\))?)\s*$", rhs)
        pre = False
        if m and lhs.count("/") == 0:
            scale, rhs = m.group(2), m.group(1)
    parts, xi = [], 0
    for sign, t in split_terms(rhs):
        mm = _TERM_HEAD.match(t)
        if mm.group(2) is None:
            b = coef["C"]
            parts.append(("+ " if b >= 0 else "- ") + fmt(abs(b)))
        else:
            x = mm.group(2).strip()
            b = coef[x.upper()]
            parts.append(("+ " if b >= 0 else "- ") + fmt(abs(b)) + " * " + x)
            xi += 1
    body = " ".join(parts)
    body = body[2:] if body.startswith("+ ") else "-" + body[2:]
    if scale is None:
        return "%s = %s" % (lhs, body)
    return ("%s = %s * (%s)" % (lhs, scale, body) if pre
            else "%s = (%s) * %s" % (lhs, body, scale))


def fit_nn_dynamic(d, start=2005, end=None, floor=0.2):
    """就業者数の式を、動学シミュレーションの誤差が小さくなるように推定する。

    【現在は使っていない】main() は論文の係数をそのまま使う。理由は main() の
    該当箇所のコメントを見ること。目的関数（失業率の2乗誤差・2005-2024年度）が
    短い窓に過剰適合し、W → UNR → N_N → W の循環の利得を小さくしすぎて、
    物価・デフレータ・就業者数が揃って悪化していた。目的関数を作り直せば
    使えるので、検証の足場として残してある。

    この式は雇用・産出比のほぼ単位根の形をしており、一期先の当てはめ（OLS）は
    よくても、動学シミュレーションでは比が実績より速く下がって雇用が過少になる。
    失業者数は労働力人口と就業者数の差なので、就業者数の1%の誤差が失業率では
    30%以上の誤差になり、賃金式の 2.414/UNR を通じてモデル全体に効く。

    そこで、この式だけは一期先ではなく、実績の外生変数を与えて比を繰り返し
    計算したときの失業率の2乗誤差を最小にする係数を探す。式の形は論文のまま。"""
    if end is None:
        end = int(d.index.max())
    rat = (d["N_N"] / d["YR"]).astype(float)
    yr = d["YR"].astype(float)
    lf = d["LF"].astype(float)
    unr_a = d["UNR"].astype(float)
    wp = (d["W"] / d["PY"]).astype(float)
    g = (wp / wp.shift(1) - 1).astype(float)
    dum = d["DUM2020"].astype(float)
    years = list(range(start, end + 1))

    def err(p):
        a, b, c = p
        r = rat.loc[start - 1]
        e = 0.0
        for y in years:
            r = a * g.loc[y] + b * r + c * dum.loc[y]
            unr = (lf.loc[y] - r * yr.loc[y]) / lf.loc[y] * 100.0
            if unr <= floor:
                return 1e9              # 失業がなくなるのは解として認めない
            e += (unr - unr_a.loc[y]) ** 2
        return e

    p = np.array([-0.005705, 0.995703, 0.000298])
    steps = [2e-5, 2e-5, 2e-6]
    for _ in range(80):
        moved = False
        for i, st in enumerate(steps):
            best = err(p)
            for s in (st, -st):
                q = p.copy()
                q[i] += s
                while err(q) < best:
                    best = err(q)
                    p = q.copy()
                    q = p.copy()
                    q[i] += s
                    moved = True
        if not moved:
            break
    return p, err(p)


def fit_w_dynamic(d, start=2005, end=None):
    """賃金式を、論文の係数を出発点に、動学シミュレーションの誤差が小さく
    なる方向へ微調整する。

    2024年度確報のデータでは、一期先の OLS で推定すると失業率の項（1/UNR）の
    係数が負（−0.61）になり、自分のラグの係数が 1 を超えた（1.009）。
    フィリップス曲線として符号が逆で、ラグ係数が1超だと賃金が自己増殖して
    動学シミュレーションが発散する。この仕組みはそのためにある。

    2023年度確報＋労働力調査の長期時系列表のデータでは、素の OLS
    でも 1/UNR が +1.87、ラグが 0.922 で、符号も安定性も問題ない。それでも
    これを使い続けているのは当てはまりのトレードオフによる。素の OLS の係数
    に替えると、1997-2023年度のファイナルテストで賃金は 2.09 → 1.67% と
    良くなるが、名目GDP 1.40 → 1.83%、GDPデフレータ 1.74 → 1.88%、失業率
    43 → 47% と、他が揃って悪くなる。賃金1本のために他を犠牲にしない、という
    N_N・GDPMAX と同じ判断である。

    やり方は、論文の係数から出発する固定幅の座標探索。1/UNR の係数を非負、
    ラグの係数を 1 未満に制約したうえで、実績の外生変数を与えて賃金を繰り返し
    計算したときの2乗誤差が下がる方向にだけ動かす。結果は論文の値から数歩
    しか動かず、ラグの係数は論文の値のままになる。つまりこの式の係数は
    独立に推定したものではなく、論文の係数を少し調整したものと読むこと。
    式の形は論文のまま。"""
    if end is None:
        end = int(d.index.max())
    W = d["W"].astype(float)
    unr = d["UNR"].astype(float)
    gap = d["GDPGAP"].astype(float)
    pc = d["PC"].astype(float)
    pch = (pc / pc.shift(1) - 1).astype(float)
    years = list(range(start, end + 1))

    def err(p):
        c0, c1, c2, c3, c4 = p
        if c1 < 0 or c4 >= 0.995:          # 符号と安定性の制約
            return 1e9
        w = W.loc[start - 1]
        e = 0.0
        for y in years:
            w = c0 + c1 / unr.loc[y] + c2 * gap.loc[y] + c3 * pch.loc[y] + c4 * w
            e += (w - W.loc[y]) ** 2
        return e

    # 論文の係数から探索を始める
    p = np.array([3.57636949552, 2.41396718284, 0.0872247680427,
                  26.3485069223, 0.903985399331])
    steps = [0.05, 0.02, 0.002, 0.2, 0.002]
    for _ in range(120):
        moved = False
        for i, st in enumerate(steps):
            best = err(p)
            for s in (st, -st):
                q = p.copy()
                q[i] += s
                while err(q) < best:
                    best = err(q)
                    p = q.copy()
                    q = p.copy()
                    q[i] += s
                    moved = True
        if not moved:
            break
    return p, err(p)


def build(lines, d, est_range=None):
    """式の形はそのままに、係数だけ手元のデータで推定し直す。

    lines は方程式体系の行のリスト。返すのは書き換えた行のリスト。"""
    y0, y1 = est_range or (1996, int(d.index.max()))
    out, n_est, fails = [], 0, []
    rows = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("'") or "=" not in s or not is_estimated(s):
            out.append(line)
            continue
        n_est += 1
        if s.lower().startswith("gdpmax"):
            # 潜在GDP は生産関数に「正常な労働時間」WHMAX と過去最大の稼働率を
            # 代入したもの（本体 4.6）。線形の形をしていないので、論文と同じく
            # 実績の労働時間 W_HOURS と稼働率 LOAD で LOG(YR) を推定し、その
            # 係数を WHMAX・LOADMAX の式に入れ直す。推定期間も論文と同じ 1994年度
            # から（データがあれば）。
            #
            # W_HOURS と LOAD の代わりに WHMAX と定数 135.6667 で推定すると、
            # 2023年度確報では資本ストックの弾力性が符号ごと反転する（論文 +0.125、
            # 2024年度確報 +0.242、2023年度確報 −0.242）。実績の労働時間と稼働率を
            # 入れると符号は戻る。念のため、弾力性が1つでも負なら論文の係数のまま残す。
            for need in ("W_HOURS", "LOAD"):
                if need not in d.columns:
                    raise ValueError("生産関数の推定に %s が要ります（fetch_misc.py）" % need)
            xs_pf = ["LOG(KN_G / PY)", "LOG(W_HOURS * N_N)", "LOG(LOAD * KN_N / PY)"]
            pf0 = max(1994, int(d.index.min()))
            r = ols("LOG(YR)", xs_pf, d, pf0, y1, const=True)
            # 実績の GDPGAP（fetch_endo.py）と同じ関数で係数を作り、モデルと
            # 実績の生産関数を一致させる。ols() の結果は R^2・DW の表に使う
            import fetch_endo as fe
            c0, a_g, b_l, g_k, loadmax = fe.production_function(
                d["YR"], d["KN_G"], d["PY"], d["W_HOURS"], d["N_N"], d["LOAD"], d["KN_N"], pf0, y1)
            c = {"C": c0, xs_pf[0]: a_g, xs_pf[1]: b_l, xs_pf[2]: g_k}
            if abs(c0 - r["coef"]["C"]) > 1e-6:
                raise ValueError("生産関数の係数が ols() と fetch_endo で違います: %s / %s" % (c0, r["coef"]["C"]))
            def term(b, expr):
                return ("+ " if b >= 0 else "- ") + fmt(abs(b)) + " * " + expr
            fitted = ("gdpmax = exp( %s %s %s %s)"
                      % (fmt(c["C"]), term(c[xs_pf[0]], "log(kn_g / py)"),
                         term(c[xs_pf[1]], "log(whmax * n_n)"),
                         term(c[xs_pf[2]], "log(%s * kn_n / py)" % fmt(loadmax))))
            rows.append(("gdpmax（生産関数 %d-%d）" % (pf0, y1), r["n"], r["adj_r2"], r["dw"]))
            elas = [c[x] for x in xs_pf]
            print("   生産関数: 政府資本 %.4f / 労働 %.4f / 稼働率×資本 %.4f（論文 0.3704 / 0.5927 / 0.1249）, LOADmax %.4f"
                  % (elas[0], elas[1], elas[2], loadmax))
            if min(elas) <= 0:
                print("   弾力性に負のものがあるので、gdpmax は論文の係数のまま残す")
                out.append(line)
            else:
                out.append(fitted)
            continue
        try:
            dep, xs, const = parse(s)
            # ols は大文字小文字を区別するが、論文の式は YDr_H のように
            # 表記が揺れている。Model と同じく大文字に揃えてから渡す。
            r = ols(dep.upper(), [x.upper() for x in xs], d, y0, y1, const=const)
            r["coef"] = dict((k.upper(), v) for k, v in r["coef"].items())
            out.append(rebuild(s, r["coef"], const))
            rows.append((s.split("=")[0].strip(), r["n"], r["adj_r2"], r["dw"]))
        except Exception as ex:
            fails.append((s.split("=")[0].strip(), str(ex)[:70]))
            out.append(line)

    print("\n推定式 %d 本のうち %d 本を推定し直した" % (n_est, len(rows)))
    if fails:
        print("\n扱えなかった式 %d 本:" % len(fails))
        for name, msg in fails:
            print("   %-22s %s" % (name, msg))
    print("\n%-24s %4s %8s %7s" % ("被説明変数", "n", "Adj.R^2", "DW"))
    for name, n, r2, dw in rows:
        print("   %-22s %3d %8.3f %7.3f" % (name, n, r2, dw))

    print("\n就業者数の式 N_N は論文の係数をそのまま使う")
    print("   （生産関数 GDPMAX は実績の労働時間・稼働率で推定し、弾力性が全部正なら書き戻す）")
    # 【この式だけ再推定しない】
    # fit_nn_dynamic() で「失業率の2乗誤差（2005-2024年度）を最小にする係数」を
    # 探す案もあった。その目的関数は窓が短すぎて、@PCH(W/PY) の係数が
    # -0.00609（論文）から -0.001985 まで小さくなった。この項は
    # W → UNR → N_N → W という循環の利得そのものなので、小さくすると賃金だけ
    # よく当たるかわりに物価・デフレータ・就業者数が揃って悪くなる。
    # 1997-2024年度のファイナルテストで係数を振って確かめた結果が下記。
    #
    #   @PCH(W/PY) の係数   YN     YR     W     PC     PY     N_N    UNR
    #   -0.001985（旧）    1.44   1.76   1.77  2.13   2.66   2.82   34.25
    #   -0.004500         1.28   1.64   2.09  1.48   1.97   2.07   31.95
    #   -0.00608893（論文） 1.31   1.54   2.87  1.19   1.63   1.77   30.71
    #
    # 7変数の平均誤差率は論文の係数が最良（1.83% 対 旧 2.20%）で、PC・PY・N_N は
    # 論文 表12 の値すら上回る。賃金は 1.77 -> 2.87% と落ちるが、それ1本の
    # ために他6本を犠牲にする理由がない。よって論文の原文をそのまま書き戻す。
    orig_nn = [l for l in lines if re.match(r"^\s*N_N\s*=", l.strip(), re.I)]
    if len(orig_nn) != 1:
        raise ValueError("論文の N_N の式が %d 本見つかりました" % len(orig_nn))
    for i, line in enumerate(out):
        if re.match(r"^\s*N_N\s*=", line, re.I):
            print("   一期先OLS : %s" % line.strip()[:96])
            print("   論文の係数 : %s" % orig_nn[0].strip()[:96])
            out[i] = orig_nn[0]
            break

    print("\n賃金式は論文の係数を出発点に、動学シミュレーションの誤差で微調整する")
    pw, ew = fit_w_dynamic(d)
    wl = ("W = %s + %s * 1 / UNR + %s * GDPGAP + %s * @PCH(PC) + %s * W(-1)"
          % (fmt(pw[0]), fmt(pw[1]), fmt(pw[2]), fmt(pw[3]), fmt(pw[4])))
    for i, line in enumerate(out):
        if re.match(r"^\s*W\s*=", line, re.I):
            print("   一期先OLS : %s" % line.strip()[:96])
            print("   制約付き動学: %s" % wl[:96])
            print("   賃金の2乗誤差 %.2f（2005-%d年度）" % (ew, int(d.index.max())))
            out[i] = wl
            break
    return out, fails


def main():
    import parkmodel as pm
    from fetch_ff import FY
    print("=" * 78)
    print("論文の推定式の係数を、%d年度確報のデータで推定し直す" % FY)
    print("=" * 78)
    d = pm.data()
    lines = open(SRC, encoding="utf-8").read().split("\n")

    print("\n--- 朴(2025c) の式体系 ---")
    out, fails = build(lines, d)

    # 朴(2026) WP65 版。差し替える行は parkmodel.WP65_LINES にまとめてある。
    # 非金融法人のポートフォリオ式は説明変数の顔ぶれが変わっているので、
    # 差し替えた形のままここで推定し直す。著者の推計期間は 2006-2023 だが、
    # ここは他の式と揃えて 1996年度〜最終年度で推定する（データが違う以上、期間だけ
    # 合わせても論文の係数には戻らない）。
    print("\n--- 朴(2026) WP65 の式体系 ---")
    wp_lines = pm.apply_wp65("\n".join(lines)).split("\n")
    for lhs, _ in pm.WP65_LINES:
        print("   差し替え  %s" % lhs)
    out2, fails2 = build(wp_lines, d)
    if fails or fails2:
        print("推定に失敗したため、既存の方程式ファイルは更新しません。")
        return 1
    for path, result in [(DST, out), (DST_WP65, out2)]:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(result))
        print("\n   %s に書き出した" % os.path.relpath(path, HERE))
    print("=" * 78)
    return 1 if (fails or fails2) else 0


if __name__ == "__main__":
    sys.exit(main())
