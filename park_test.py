"""park_test.py -- 論文モデルのパーシャルテストとファイナルテスト。

朴(2025c) はこの2つを次のように説明している（本体 5.10）。

  パーシャルテスト  それぞれの内生変数の方程式に、各期の外生変数と先決内生変数を
                    代入するだけの計算
  ファイナルテスト  内生変数の方程式に、計算された内生変数をも用いた計算

パーシャルテストは同時決定を解かない。1本ずつ、右辺にすべて実績値を入れて
左辺を1回計算し、実績と比べる。式ごとの当てはまりを見るためのもので、
モデル全体の安定性とは関係がない。

ファイナルテストは、初期値だけ実績にして、あとはモデルが計算した値を使って
繰り返す。こちらはモデル全体の性質が出る。
"""
import os
import sys

import numpy as np
import pandas as pd

import parkmodel as pm
from sfcsim import _NS


def partial(m, d, start, end, way="onepass"):
    """パーシャルテスト。同時決定は解かず、1回だけ計算する。

    way="onepass"    ブロックの順に1回ずつ解く。当期の内生変数が右辺に来る
                     ところには、その回で計算された値を使う。論文の「各期の
                     外生変数と先決内生変数を代入するだけの計算」はこちら。
                     定義式にも推定式の誤差が伝わるので、名目GDPのような
                     集計変数にも誤差が出る。
    way="substitute" 右辺をすべて実績にして1本ずつ計算する。式ごとの当てはまり
                     だけを見たいときに使う。定義式は必ず誤差ゼロになる。
    """
    idx = list(d.index)
    out = pd.DataFrame(index=d.loc[start:end].index, columns=m.endog, dtype=float)
    order = [v for b in m.blocks() for v in b] if way == "onepass" else m.endog
    for t in out.index:
        i = idx.index(t)

        def lagfun(nm, k, i=i):
            return float(d.at[idx[i - k], nm])

        cur = dict((c, float(d.at[t, c])) for c in d.columns)
        ns = _NS(cur, lagfun)
        for v in order:
            eq = m.by_lhs[v]
            keep = cur[v]
            try:
                m._assign(eq, eval(eq.code, {"__builtins__": {}}, ns), cur, lagfun)
                out.at[t, v] = cur[v]
            except Exception:
                out.at[t, v] = np.nan
                cur[v] = keep
                continue
            if way == "substitute":
                cur[v] = keep                  # 他の式には実績を使う
    return out


def errors(sim, act, names, start, end):
    rows = []
    for v in names:
        if v not in sim.columns or v not in act.columns:
            continue
        a = act[v].loc[start:end]
        s = sim[v].loc[start:end]
        ok = np.isfinite(a) & np.isfinite(s) & (a.abs() > 1e-9)
        if ok.sum() == 0:
            continue
        rows.append((v, float(((s[ok] - a[ok]).abs() / a[ok].abs() * 100).mean()), int(ok.sum())))
    rows.sort(key=lambda r: r[1])
    return rows


MAIN = ["YR", "YN", "CR", "IR_N", "IR_H", "MR", "XR", "PC", "PY", "PX", "PM",
        "W", "N_N", "UNR", "TIN_N", "TD_N", "T_H", "B2", "YD_H", "Y_H",
        "S_H", "S_N", "NL_G", "NL_H", "NNFWA_H", "NNFWA_G", "GDPGAP"]


def compare_with_paper(mine, table="t11"):
    """論文の表11（パーシャル）または表12（ファイナル）と突き合わせる。"""
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "paper"))
    if table == "t11":
        from paper_table11 import PAPER_T11 as ref
    else:
        from paper_table12 import PAPER_T12 as ref
    rows = [(v, ref[v], mine[v]) for v in ref if v in mine]
    rows.sort(key=lambda r: -abs(r[1] - r[2]))
    return rows


def longest_final(m, d, starts=(1997, 2000, 2005, 2010, 2015, 2018)):
    """ファイナルテストが何年度まで続くかを、開始年ごとに調べる。

    このモデルは失業者数 UN が労働力人口と就業者数の差として決まるため、
    就業者数がわずかにずれると失業率が大きく動き、そこから賃金式の
    2.414/UNR を通じて全体に効く。動学シミュレーションではこれが積み重なり、
    途中で解けなくなることがある。論文でも UN と UNR の誤差率は 48% 前後で、
    構造に由来する脆さである。"""
    out = []
    for st in starts:
        # 正常時は全期間を一度だけ解く。失敗時のみ終点を伸ばして診断する。
        final_end = int(d.index.max())
        try:
            m.simulate(d, st, final_end, mode="dynamic", maxit=5000, tol=1e-7)
        except Exception:
            pass
        else:
            out.append((st, final_end, final_end - st + 1))
            continue
        last = None
        for end in range(st, int(d.index.max()) + 1):
            try:
                m.simulate(d, st, end, mode="dynamic", maxit=5000, tol=1e-7)
                last = end
            except Exception:
                break
        out.append((st, last, (last - st + 1) if last else 0))
    return out


def main():
    start, end = 1997, 2023           # 論文 表11 と同じ期間
    print("=" * 74)
    print("パーシャルテスト（%d-%d年度）" % (start, end))
    print("=" * 74)
    m, d = pm.load(version=1, coeffs="reest")
    sim = partial(m, d, start, end, way="onepass")

    rows = errors(sim, d, m.endog, start, end)
    print("\n内生169本のうち %d 本で誤差率を計算できた" % len(rows))
    good = [r for r in rows if r[1] < 5]
    print("平均絶対誤差率が 5%% 未満: %d 本 / 10%% 未満: %d 本"
          % (len(good), len([r for r in rows if r[1] < 10])))

    print("\n主要変数")
    print("   %-10s %10s" % ("変数", "平均絶対誤差率"))
    for v, e, n in errors(sim, d, MAIN, start, end):
        print("   %-10s %9.3f%%" % (v, e))

    print("\n誤差の大きい10本")
    for v, e, n in rows[-10:]:
        print("   %-12s %10.2f%%" % (v, e))

    mine = dict((v, e) for v, e, n in rows)
    cmp_rows = compare_with_paper(mine, "t11")
    if cmp_rows:
        diff = [abs(p - q) for _, p, q in cmp_rows]
        close = [1 for _, p, q in cmp_rows if abs(p - q) <= max(1.0, 0.5 * p)]
        print("\n論文 表11（本体 p.45）との突き合わせ")
        print("   比較できた変数        %d 本" % len(cmp_rows))
        print("   誤差率の差の中央値    %.2f %%pt" % float(np.median(diff)))
        print("   近い（±1%%pt か半分以内）%d 本" % len(close))
        print("\n   差の大きい8本")
        print("      %-12s %9s %9s" % ("変数", "論文", "本実装"))
        for v, p_, q_ in cmp_rows[:8]:
            print("      %-12s %8.2f%% %8.2f%%" % (v, p_, q_))

    sim.round(6).to_csv("park_partial.csv", encoding="utf-8-sig")
    print("\n   park_partial.csv に保存した")

    print("\n" + "=" * 74)
    print("ファイナルテスト")
    print("=" * 74)
    runs = longest_final(m, d)
    print("\n   開始年ごとに、何年度まで続くか")
    for st, last, n in runs:
        print("      %d年度から → %s まで（%d年間）" % (st, last, n))
    if not runs or any(last != int(d.index.max()) for _, last, _ in runs):
        print("失敗: 全開始年から最終年度まで完走する必要があります。")
        return 1
    best = max(runs, key=lambda r: r[2])
    st, last, n = best
    print("\n   最長は %d-%d年度（%d年間）。ここで誤差率を出す。" % (st, last, n))
    fsim = m.simulate(d, st, last, mode="dynamic", maxit=5000, tol=1e-7)
    frows = errors(fsim, d, m.endog, st, last)
    fmine = dict((v, e) for v, e, k in frows)
    print("\n   主要変数（参考: 論文 表12 は 1997-2023年度）")
    print("      %-10s %9s %9s" % ("変数", "論文", "本実装"))
    for v, e, k in errors(fsim, d, MAIN, st, last):
        ref = compare_with_paper({v: e}, "t12")
        p_ = ref[0][1] if ref else None
        print("      %-10s %8s %8.2f%%"
              % (v, ("%.2f%%" % p_) if p_ is not None else "-", e))
    fsim.round(6).to_csv("park_final.csv", encoding="utf-8-sig")
    print("\n   park_final.csv に保存した")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
