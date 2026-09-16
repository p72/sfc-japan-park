"""park_check.py -- 論文の方程式体系が sfcsim で読めることを確認する。

paper/park2025c_model.eq は朴(2025c) 巻末の EViews モデル方程式を
機械抽出したもの。ここではそれを sfcsim.Model に読ませて、

  1. 169本すべてがパースできること
  2. 大文字小文字だけが違う同名変数が残っていないこと
  3. 内生・外生の本数が論文と整合すること
  4. ブロック三角化が通り、同時決定ブロックが求まること

を確認する。終了コード 0 なら健全。モデルを解くにはまだ外生変数の
データが要るので、ここでは「解ける形になっているか」までを見る。
"""
import pathlib
import sys
import collections

from sfcsim import Model

EQ_FILE = pathlib.Path(__file__).with_name("paper") / "park2025c_model.eq"
N_EQ = 169                       # 論文 p.82-89 から抽出した本数

fail = []


def check(label, cond, detail=""):
    print("   %-42s %s" % (label, "OK" if cond else "NG"), detail)
    if not cond:
        fail.append(label)


print("=" * 76)
print("朴(2025c) 方程式体系の読み込みチェック")
print("=" * 76)

text = EQ_FILE.read_text(encoding="utf-8")
lines = [l for l in text.split("\n") if l.strip() and not l.startswith("'")]

print("\n[1] 1本ずつパースする")
bad = []
for line in lines:
    try:
        Model(line, fold_case=True)
    except Exception as ex:
        bad.append((line.split("=")[0].strip(), str(ex)[:60]))
for name, msg in bad:
    print("     失敗:", name, "→", msg)
check("式の本数", len(lines) == N_EQ, "%d 本" % len(lines))
check("全式がパースできる", not bad, "失敗 %d 本" % len(bad))

print("\n[2] 体系として組む（fold_case=True）")
m = Model(text, name="park2025c", fold_case=True)
allv = list(m.endog) + m.exog()
g = collections.defaultdict(set)
for v in allv:
    g[v.lower()].add(v)
dup = [sorted(v) for v in g.values() if len(v) > 1]
check("内生変数の本数", len(m.endog) == N_EQ, "%d 本" % len(m.endog))
check("大小違いの同名変数が無い", not dup, "%d 組" % len(dup))
for d in dup[:5]:
    print("     衝突:", d)

print("\n[3] 大小を区別しないと壊れることの確認")
m_bad = Model(text, name="park2025c_nofold", fold_case=False)
check("fold_case=False では外生が水増しされる",
      len(m_bad.exog()) > len(m.exog()),
      "%d → %d 本" % (len(m_bad.exog()), len(m.exog())))

print("\n[4] ブロック三角化")
blocks = m.blocks()
sizes = [len(b) for b in blocks]
sim = [s for s in sizes if s > 1]
check("ブロック三角化が通る", len(blocks) > 0, "%d ブロック" % len(blocks))
check("同時決定ブロックがある", bool(sim), "最大 %d 変数" % (max(sizes) if sizes else 0))

print("\n[5] 集計")
print("     内生変数 %d ／ 外生変数 %d ／ 変数総数 %d"
      % (len(m.endog), len(m.exog()), len(allv)))
print("     ブロック %d（同時決定 %s）" % (len(blocks), sim))

print("\n[6] 外生変数のデータ充足状況")
import pandas as pd
have = set()
for f in ["japan_ff_stock_fy.csv", "japan_ff_flow_fy.csv",
          "japan_ff_cg_fy.csv", "japan_ff_share_fy.csv",
          "japan_sector_fy.csv", "japan_misc_fy.csv",
          "japan_resid_fy.csv", "japan_fincome_fy.csv"]:
    q = pathlib.Path(__file__).with_name(f)
    if q.exists():
        have |= set(c.upper() for c in
                    pd.read_csv(q, index_col=0, encoding="utf-8-sig").columns)
ex = set(m.exog())
got = sorted(ex & have)
check("外生変数のデータが全部そろっているか", not (ex - have), "%d / %d 本" % (len(got), len(ex)))
if ex - have:
    print("     不足:", sorted(ex - have))

print("\n" + "=" * 76)
if fail:
    print("失敗:", ", ".join(fail))
    sys.exit(1)
print("すべて通過")
print("=" * 76)
