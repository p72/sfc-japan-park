"""
sfcsim.py -- EViews の「モデルオブジェクト＋ソルバー」相当の最小実装 (v2)

依存は numpy / pandas のみ。

朴(2025c/2026)の SFC マクロ計量モデル（内生169本・外生112本）の方程式を
EViews の表記のまま貼り付けて解くことを想定している。

対応する記法:
  X(-1)          ラグ
  LOG(X) = ...   左辺の変換（LOG / D）は自動で逆変換される
  D(X)           階差
  @PCH(X)        変化率 (X-X(-1))/X(-1)
  @LOG @EXP @ABS @SQRT
  '              コメント（EViews と同じ）

主な機能:
  Model.blocks()      ブロック三角化（EViews の block structure 相当）
  Model.simulate()    static=パーシャルテスト / dynamic=ファイナルテスト
  ols(), mape()
"""
import re
import numpy as np
import pandas as pd

# ================================================================ 式の翻訳
_ATFUN = re.compile(r"@(LOG|EXP|ABS|SQRT)\b", re.I)
_LAG = re.compile(r"\b([A-Za-z_]\w*)\s*\(\s*-\s*(\d+)\s*\)")
# D( と @PCH( の呼び出し開始位置。引数は式でもよいので括弧の対応で切り出す。
_CALL = re.compile(r"(@PCHY?|\bD)\s*\(", re.I)
# 翻訳後に残ってはいけない関数呼び出しの検出用
_RESID = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
# ラグ済みの参照か、素の識別子か
_SHIFT = re.compile(r"_L\('(\w+)',(\d+)\)|\b([A-Za-z_]\w*)\b")

_FUNCS = {"log", "exp", "sqrt", "abs", "min", "max", "_L"}
_FUNCS_LC = set(f.lower() for f in _FUNCS)      # 大文字小文字を無視した突き合わせ用


def _close_paren(s, i):
    """s[i] が '(' のとき、対応する ')' の位置を返す。"""
    depth = 0
    for j in range(i, len(s)):
        if s[j] == "(":
            depth += 1
        elif s[j] == ")":
            depth -= 1
            if depth == 0:
                return j
    raise ValueError("括弧が閉じていません: %r" % s)


def _shift(code, k):
    """翻訳済みの式を k 期ラグさせる。

    素の変数 X は _L('X',k) に、既にラグしている _L('X',n) は
    _L('X',n+k) になる。関数名（log など）はそのまま残す。"""
    def sub(m):
        if m.group(1) is not None:                 # 既存のラグ参照
            return "_L('%s',%d)" % (m.group(1), int(m.group(2)) + k)
        name = m.group(3)
        if name.lower() in _FUNCS:                 # 関数名はラグしない
            return name
        return "_L('%s',%d)" % (name, k)
    return _SHIFT.sub(sub, code)


def _expand(expr):
    """D(式) と @PCH(式) を、引数が式であっても展開する。

    引数をさきに翻訳してから式ごと1期ラグさせるので、
    D(TIN_N/YR) や @PCH(W/PY)、d(LOG(YR)) のような形も扱える。"""
    m = _CALL.search(expr)
    if m is None:
        return expr
    open_i = expr.index("(", m.end() - 1)
    close_i = _close_paren(expr, open_i)
    arg = expr[open_i + 1:close_i]
    cur = _LAG.sub(lambda g: "_L('%s',%s)" % (g.group(1), g.group(2)),
                   _expand(arg))                   # 引数の中の D/@PCH も展開
    prev = _shift(cur, 1)
    if m.group(1).upper().startswith("@PCH"):
        rep = "((%s)-(%s))/(%s)" % (cur, prev, prev)
    else:
        rep = "(%s)-(%s)" % (cur, prev)
    return expr[:m.start()] + "(" + rep + ")" + _expand(expr[close_i + 1:])


def translate(expr):
    """EViews 式 -> Python 式。ラグ参照は _L('NAME', k) 呼び出しになる。"""
    expr = expr.replace("^", "**")
    expr = _ATFUN.sub(lambda m: m.group(1).lower(), expr)          # @LOG -> log
    expr = _expand(expr)                                           # D(...) / @PCH(...)
    expr = _LAG.sub(lambda m: "_L('{0}',{1})".format(m.group(1), m.group(2)), expr)
    left = sorted(set(n for n in _RESID.findall(expr) if n.lower() not in _FUNCS_LC))
    if left:
        # ここを素通りさせると、関数名が外生変数として扱われて黙って壊れる
        raise ValueError("未対応の関数呼び出しが残りました: %s" % ", ".join(left))
    return expr


def deps_of(code_str):
    """翻訳済み式から (当期依存, ラグ依存) の変数名集合を取り出す。"""
    lagged = set(re.findall(r"_L\('(\w+)',\d+\)", code_str))
    stripped = re.sub(r"_L\('\w+',\d+\)", " ", code_str)
    cur = set(n for n in re.findall(r"\b([A-Za-z_]\w*)\b", stripped)
              if n.lower() not in _FUNCS)
    return cur, lagged


_BUILTIN_FUNCS = {"log": np.log, "exp": np.exp, "sqrt": np.sqrt,
                  "abs": abs, "min": min, "max": max}

# 減衰を強めて解き直す対象。反復の途中で起きる数値計算上の失敗だけ
# （_solve_year の docstring 参照）。
_RETRY_ERRORS = (RuntimeError, ZeroDivisionError, OverflowError, FloatingPointError)


class _NS(dict):
    """eval 用の名前空間。未定義名は当期値テーブルから引く。

    EViews は大文字小文字を区別しないので、LOG / Log / log をすべて受ける
    （論文の式は LOG(...) と大文字で書かれている）。"""
    def __init__(self, cur, lagfun):
        super().__init__(_L=lagfun, **_BUILTIN_FUNCS)
        self._cur = cur

    def __missing__(self, key):
        try:
            return self._cur[key]
        except KeyError:
            pass
        fn = _BUILTIN_FUNCS.get(key.lower())
        if fn is not None:
            return fn
        raise NameError("変数 '%s' が未定義です（外生変数の入れ忘れ？）" % key)


# ================================================================ モデル
class Eq(object):
    __slots__ = ("lhs", "kind", "raw", "code", "cur_deps", "lag_deps")

    def __init__(self, lhs, kind, raw, code, cur_deps, lag_deps):
        self.lhs, self.kind, self.raw = lhs, kind, raw
        self.code, self.cur_deps, self.lag_deps = code, cur_deps, lag_deps


_LHS_LOG = re.compile(r"^\s*@?LOG\(\s*([A-Za-z_]\w*)\s*\)\s*$", re.I)
_LHS_D = re.compile(r"^\s*D\(\s*([A-Za-z_]\w*)\s*\)\s*$", re.I)
_LHS_BARE = re.compile(r"^\s*([A-Za-z_]\w*)\s*$")
# 左辺が比率の式（論文のポートフォリオ選択式）。X/Y = f は X = f*Y と同じ。
_LHS_RATIO = re.compile(r"^\s*([A-Za-z_]\w*)\s*/\s*(\S.*?)\s*$")


class Model(object):
    """EViews のモデルオブジェクト相当。

    fold_case=True にすると、変数名を大文字に正規化して大文字小文字の
    違いを無視する（EViews と同じ扱い）。論文の方程式体系は Cr と CR、
    In_N と IN_N のように同じ変数が別表記で現れるので、貼り付けて解く
    場合は必ずこれを有効にすること。無効のままだと別変数として扱われ、
    本来内生の変数が外生に化けて黙って壊れる。
    このとき与えるデータの列名も大文字にしておく必要がある。"""

    def __init__(self, text, name="model", fold_case=False):
        self.name = name
        self.fold_case = fold_case
        self.eqs = []
        for raw in text.splitlines():
            line = raw.split("'")[0].strip()
            if not line or "=" not in line:
                continue
            if fold_case:
                line = line.upper()
            lhs_txt, rhs = line.split("=", 1)
            rhs = rhs.strip()
            m = _LHS_LOG.match(lhs_txt)
            if m:
                lhs, kind = m.group(1), "log"        # LOG(X)=f -> X=exp(f)
            else:
                m = _LHS_D.match(lhs_txt)
                if m:
                    lhs, kind = m.group(1), "diff"   # D(X)=f -> X=X(-1)+f
                else:
                    m = _LHS_BARE.match(lhs_txt)
                    if m:
                        lhs, kind = m.group(1), "level"
                    else:
                        m = _LHS_RATIO.match(lhs_txt)
                        if not m:
                            raise ValueError("左辺を解釈できません: %r" % raw)
                        # X/Y = f  ->  X = (f)*(Y)
                        lhs, kind = m.group(1), "level"
                        rhs = "(%s)*(%s)" % (rhs, m.group(2))
            tr = translate(rhs)
            cur, lag = deps_of(tr)
            self.eqs.append(Eq(lhs, kind, line, compile(tr, "<eq>", "eval"),
                               cur, lag))
        self.endog = [e.lhs for e in self.eqs]
        # 解として受け入れてよいかを判定する関数（任意）。1時点ぶんの解を
        # 受け取って True / False を返す。非線形なので同じ年に複数の解が
        # あることがあり、そのうち「定義の外」のものを弾くために使う。
        # 式そのものには手を入れない（AGENTS.md の1番目）。parkmodel が
        # 失業者数が負の解を弾く関数を入れている。
        self.accept = None
        if len(set(self.endog)) != len(self.endog):
            dup = [v for v in set(self.endog) if self.endog.count(v) > 1]
            raise ValueError("同じ内生変数に複数の方程式があります: %s" % dup)
        self.by_lhs = dict((e.lhs, e) for e in self.eqs)
        self._blocks = None

    def exog(self):
        """方程式に現れるが左辺にない変数＝外生変数。"""
        used = set()
        for e in self.eqs:
            used |= e.cur_deps | e.lag_deps
        return sorted(used - set(self.endog))

    # ------------------------------------------------- ブロック三角化 (Tarjan)
    def blocks(self):
        """当期依存グラフの強連結成分を、解くべき順に返す。
        EViews が内部で行う block structure 分析と同じもの。"""
        if self._blocks is not None:
            return self._blocks
        endo = set(self.endog)
        # 集合をそのまま回すと、文字列ハッシュのランダム化で並び順が実行の
        # たびに変わる。ガウス・ザイデルは掃く順番で収束が変わるので、
        # 方程式ファイルに書かれた順（＝論文の並び）に固定しておく。
        pos = dict((v, i) for i, v in enumerate(self.endog))
        g = dict((e.lhs, tuple(sorted((e.cur_deps & endo) - set([e.lhs]),
                                      key=lambda w: pos[w])))
                 for e in self.eqs)
        idx, low, on, stack, out, cnt = {}, {}, set(), [], [], [0]

        def strong(v):                    # 反復版 Tarjan（169本では再帰は危険）
            work = [(v, iter(g[v]))]
            idx[v] = low[v] = cnt[0]; cnt[0] += 1
            stack.append(v); on.add(v)
            while work:
                node, it = work[-1]
                advanced = False
                for w in it:
                    if w not in idx:
                        idx[w] = low[w] = cnt[0]; cnt[0] += 1
                        stack.append(w); on.add(w)
                        work.append((w, iter(g[w])))
                        advanced = True
                        break
                    elif w in on:
                        low[node] = min(low[node], idx[w])
                if advanced:
                    continue
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[node])
                if low[node] == idx[node]:
                    comp = []
                    while True:
                        w = stack.pop(); on.discard(w); comp.append(w)
                        if w == node:
                            break
                    out.append(comp)

        for v in self.endog:
            if v not in idx:
                strong(v)
        self._blocks = out                # Tarjan の出力順がそのまま解く順
        return out

    def block_report(self):
        bl = self.blocks()
        sim = [b for b in bl if len(b) > 1]
        selfref = [b for b in bl if len(b) == 1
                   and b[0] in self.by_lhs[b[0]].cur_deps]
        rec = [b for b in bl if len(b) == 1
               and b[0] not in self.by_lhs[b[0]].cur_deps]
        lines = ["方程式 %d 本 / ブロック %d 個" % (len(self.eqs), len(bl)),
                 "  逐次ブロック（代入するだけ）: %d" % len(rec),
                 "  自己参照の1本ブロック      : %d" % len(selfref),
                 "  同時決定ブロック           : %d" % len(sim)]
        for b in sorted(sim, key=len, reverse=True)[:5]:
            names = sorted(b)
            lines.append("    - サイズ %d: %s%s"
                         % (len(b), ", ".join(names[:12]),
                            " ..." if len(names) > 12 else ""))
        return "\n".join(lines)

    # ------------------------------------------------- 求解
    def _assign(self, eq, val, cur, lagfun):
        if eq.kind == "log":
            value = float(np.exp(val))
        elif eq.kind == "diff":
            value = lagfun(eq.lhs, 1) + val
        else:
            value = val
        if not np.isfinite(value):
            raise RuntimeError("%s の計算値が有限値ではありません: %s" % (eq.lhs, value))
        cur[eq.lhs] = value

    def _solve_block(self, blk, cur, ns, lagfun, method, tol, maxit, damp):
        eqs = [self.by_lhs[v] for v in blk]
        if len(eqs) == 1 and blk[0] not in eqs[0].cur_deps:      # 逐次ブロック
            self._assign(eqs[0], eval(eqs[0].code, {"__builtins__": {}}, ns),
                         cur, lagfun)          # 非数の検査は _assign の中
            return 1
        if method == "gauss-seidel":
            for it in range(maxit):
                err = 0.0
                for eq in eqs:
                    old = cur[eq.lhs]
                    self._assign(eq, eval(eq.code, {"__builtins__": {}}, ns),
                                 cur, lagfun)
                    new = cur[eq.lhs]
                    if not np.isfinite(new):
                        # max(0.0, nan) は 0.0 を返すので、放っておくと誤差ゼロと
                        # 見なされて「収束した」ことになってしまう。
                        raise RuntimeError(
                            "%s の計算値が数値になりません（%d 回目、ブロック %d 変数）"
                            % (eq.lhs, it + 1, len(blk)))
                    err = max(err, abs(new - old) / max(1.0, abs(old)))
                    cur[eq.lhs] = old + damp * (new - old)
                if err < tol:
                    return it + 1
            raise RuntimeError("ブロック %s が %d 回で収束せず (err=%.2e)"
                               % (blk, maxit, err))
        # --- Newton 法（数値ヤコビアン）---
        names = [e.lhs for e in eqs]

        def F(x):
            for n, v in zip(names, x):
                cur[n] = v
            r = []
            for n, eq in zip(names, eqs):
                keep = cur[n]
                self._assign(eq, eval(eq.code, {"__builtins__": {}}, ns),
                             cur, lagfun)
                r.append(keep - cur[n])
                cur[n] = keep
            return np.array(r, dtype=float)

        x = np.array([cur[n] for n in names], dtype=float)
        for it in range(maxit):
            f0 = F(x)
            if np.max(np.abs(f0) / np.maximum(1.0, np.abs(x))) < tol:
                for n, v in zip(names, x):
                    cur[n] = v
                return it + 1
            J = np.empty((len(x), len(x)))
            for j in range(len(x)):
                h = 1e-6 * max(1.0, abs(x[j]))
                xp = x.copy(); xp[j] += h
                J[:, j] = (F(xp) - f0) / h
            x = x - damp * np.linalg.solve(J, f0)
        raise RuntimeError("ブロック %s で Newton が収束せず" % blk)

    def _solve_year(self, blocks, cur, ns, lagfun, method, tol, maxit, damp, init):
        """1時点ぶんを解く。発散したら減衰を強めて解き直す。

        Gauss-Seidel は、賃金式の 2.414/UNR のように傾きの急な項があると
        行きすぎて発散することがある。式のほうに上限・下限を足せば止まるが、
        それをやると論文のモデルではなくなる（AGENTS.md の1番目）。解そのものは
        存在するので、ここでは**式は一切変えず**、減衰を半分ずつ強めて解き直す。
        減衰を強めるぶん収束は遅くなるので、反復の上限も同じ比率で伸ばす。

        失敗した回の途中経過を残すと次の試行の初期値が壊れるので、毎回
        init（その年の初期値）から引き直す。cur は _NS が参照を握っている
        ため、新しい辞書に差し替えず中身を入れ替える。

        解き直すのは、反復の途中で起きる数値計算上の失敗だけである。収束しない
        （RuntimeError）ほかに、Python の浮動小数点除算のゼロ除算
        （ZeroDivisionError。np.errstate では抑えられない）、桁あふれ
        （OverflowError）、FloatingPointError を含める。変数の入れ忘れ
        （NameError）や型の誤り（TypeError）は入力の誤りなので、隠さずそのまま上げる。

        返り値は (ブロックごとの反復回数, 実際に使った減衰)。
        """
        last, d = None, damp
        for _ in range(4):
            cur.clear()
            cur.update(init)
            mx = int(maxit * damp / d)
            try:
                # 失敗する試行では log(負) などが出るが、有限性は _assign が
                # 明示的に検査している。警告で出力を埋めないよう黙らせる。
                with np.errstate(all="ignore"):
                    its = [self._solve_block(b, cur, ns, lagfun, method, tol, mx, d)
                           for b in blocks]
                if self.accept is not None and not self.accept(cur):
                    raise RuntimeError("解が受け入れ条件を満たしません")
                return its, d
            except _RETRY_ERRORS as ex:
                last = ex
                d /= 2.0
        raise last

    def simulate(self, data, start, end, mode="dynamic",
                 method="gauss-seidel", tol=1e-9, maxit=2000, damp=1.0,
                 verbose=False):
        """
        mode='static'  ラグ項に実績値   -> パーシャルテスト
        mode='dynamic' ラグ項に解いた値 -> ファイナルテスト（反実仮想はこちら）
        """
        if mode not in ("static", "dynamic"):
            raise ValueError("mode は static または dynamic を指定してください")
        if method not in ("gauss-seidel", "newton"):
            raise ValueError("method は gauss-seidel または newton を指定してください")
        if not np.isfinite(tol) or tol <= 0:
            raise ValueError("tol は正の有限値を指定してください")
        if isinstance(maxit, bool) or not isinstance(maxit, (int, np.integer)) or maxit < 1:
            raise ValueError("maxit は正の整数を指定してください")
        if not np.isfinite(damp) or not 0 < damp <= 1:
            raise ValueError("damp は 0 より大きく 1 以下を指定してください")
        if not data.index.is_unique or not data.index.is_monotonic_increasing:
            raise ValueError("データの時点は重複のない昇順にしてください")
        if not data.columns.is_unique:
            raise ValueError("データの列名が重複しています")
        if start not in data.index or end not in data.index:
            raise ValueError("開始・終了時点がデータにありません")
        if data.index.get_loc(start) > data.index.get_loc(end):
            raise ValueError("開始時点は終了時点以前にしてください")
        sim = data.copy()
        for v in self.endog:
            if v not in sim.columns:
                sim[v] = np.nan
        idx = list(sim.index)
        i0, i1 = idx.index(start), idx.index(end)
        lag_src = data if mode == "static" else sim
        blocks = self.blocks()

        for i in range(i0, i1 + 1):
            t = idx[i]

            def lagfun(nm, k, i=i):
                if i - k < 0:
                    raise IndexError("%s(-%d) がサンプル開始より前です" % (nm, k))
                return float(lag_src.at[idx[i - k], nm])

            init = {}
            for v in self.endog:
                val = sim.at[t, v]
                if not np.isfinite(val):
                    val = sim.at[idx[i - 1], v] if i > 0 else 1.0
                init[v] = float(val) if np.isfinite(val) else 1.0
            for c in sim.columns:                    # 外生変数
                if c not in init:
                    v = sim.at[t, c]
                    try:
                        init[c] = float(v)
                    except (TypeError, ValueError):
                        # None や文字列の列を黙って通すと、ずっと先で意味の
                        # 分からない例外になる。どの列かをここで言う。
                        raise ValueError(
                            "外生変数 %s の %s 時点の値が数値ではありません: %r"
                            % (c, t, v))
            cur = dict(init)
            ns = _NS(cur, lagfun)
            its, used = self._solve_year(blocks, cur, ns, lagfun,
                                         method, tol, maxit, damp, init)
            if verbose:
                print("  t=%s: 最大反復 %d 回%s"
                      % (t, max(its),
                         "" if used == damp else "（減衰 %.3f で解き直し）" % used))
            for v in self.endog:
                sim.at[t, v] = cur[v]
        return sim


# ================================================================ 補助関数
def ols(y_expr, x_exprs, data, start=None, end=None, const=True):
    """numpy だけで OLS。EViews の方程式推定の代わり。"""
    d = data.loc[start:end]
    idx = list(data.index)

    def build(expr):
        code = compile(translate(expr), "<x>", "eval")
        out = []
        for t in d.index:
            i = idx.index(t)
            cur = dict((c, float(data.at[t, c])) for c in data.columns)

            def lag(nm, k, i=i):
                # idx[i-k] が負になると Python は末尾から数えるので、
                # サンプル先頭より前のラグが黙って最終年の値になる。
                if i - k < 0:
                    raise IndexError("%s(-%d) がサンプル開始より前です" % (nm, k))
                return float(data.at[idx[i - k], nm])
            out.append(eval(code, {"__builtins__": {}}, _NS(cur, lag)))
        return np.array(out, dtype=float)

    y = build(y_expr)
    cols = [build(e) for e in x_exprs]
    names = list(x_exprs)
    if const:
        cols.insert(0, np.ones_like(y))
        names.insert(0, "C")
    X = np.column_stack(cols)
    ok = np.isfinite(y) & np.isfinite(X).all(1)
    y, X = y[ok], X[ok]
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    n, k = X.shape
    se = np.sqrt(np.diag((e @ e / (n - k)) * np.linalg.inv(X.T @ X)))
    r2 = 1 - (e @ e) / ((y - y.mean()) @ (y - y.mean()))
    return {"coef": dict(zip(names, b)), "se": dict(zip(names, se)),
            "adj_r2": 1 - (1 - r2) * (n - 1) / (n - k),
            "dw": float(np.sum(np.diff(e) ** 2) / (e @ e)), "n": n}


def mape(sim, act, vars_, start=None, end=None):
    """平均絶対誤差率(%)。論文の表11・表12 と同じ指標。"""
    s, a = sim.loc[start:end, vars_], act.loc[start:end, vars_]
    return (100 * ((s - a) / a.replace(0, np.nan)).abs()).mean().rename("MAPE(%)")
