"""sanity_park.py -- 論文モデルの前向きシミュレーションの健全性チェック。

  python sanity_park.py [年数]          既定は10年（データの最終年度の翌年から）
  python sanity_park.py [年数] --hold   名目フローを名目額で据え置く
  python sanity_park.py [年数] --wp65  朴(2026) WP65 の変更点を入れた式で解く

過去の再現（park_test.py のファイナルテスト）が通っても、前向きにしか出ない
欠陥は見つからない。逆もまた然り。この2つは別のものを検証する。

朴(2025c) は前向きシミュレーションを行っていないので、ここから先は論文の
範囲外である。外生変数の将来値の置き方は forecast.py の docstring を見ること。

チェックの中身
  [0] 方程式が論文から変わっていないか   ← 最初に必ず確認する
  [1] そもそも解けるか
  [2] ストックとフローの整合
  [3] 発散していないか
  [4] 値が経済的にありうる範囲か

[0] について
  前向きが解けないとき、式に上限・下限や減衰項を足せば「解ける」ようになる。
  それをやった瞬間に論文のモデルではなくなる。そうならないよう、係数の値も
  符号も潰した「骨格」を論文の原文と突き合わせ、既知の差以外が出たら止める。

  既知の差は次のものだけである。
    1. バージョン1のスイッチ（RrB を外生にし、NGBA_CB を内生にする）
       これは論文自身が用意した切替であって、こちらの改造ではない
    2. 失業率の下限（UNR = MAX(UN/LF*100, UNR_FLOOR)）
       既定では入れない（2026-09-12 以降）。unr_floor=2.0 を渡したときだけ出る
    3. マネーストックの定義（海外部門を除く）
       巻末コードは古く、朴(2026a) 5節が本文で新しい定義を明記している
    4. wp65=True のときのみ、WP65 付録が明記した変更点5本
       （営業余剰の残余式化、日銀純貸出の政府移転、法人ポートフォリオ2本）
"""
import difflib
from collections import Counter
import io
import os
import re
import sys

import numpy as np

import forecast as fc
import parkmodel as pm

HERE = os.path.dirname(os.path.abspath(__file__))
PAPER_EQ = os.path.join(HERE, "paper", "park2025c_model.eq")

SECTORS = ["N", "CB", "F", "G", "H", "W"]

# [0] で許す差。左が論文にあって消えた行、右が足された行。
KNOWN_REMOVED = ["RRB=RRB(-1)+#*NGBA_SUM", "UNR=UN/LF*#",
                 "MS=NGSHA_N+NGSHA_H+NGSHA_W+NDEPA_N+NDEPA_G+NDEPA_H+NDEPA_W"]
KNOWN_ADDED = ["NGBA_CB=-(NGBA_N+NGBA_F+NGBA_G+NGBA_H+NGBA_W)",
               "UNR=MAX(UN/LF*#,UNR_FLOOR)",
               "MS=NGSHA_N+NGSHA_H+NDEPA_N+NDEPA_G+NDEPA_H"]

# 差が出たときに何と呼ぶか。載っていないものは WP65 の変更点として数える。
KNOWN_LABEL = {
    "RRB=RRB(-1)+#*NGBA_SUM": "バージョン1のスイッチ",
    "UNR=UN/LF*#": "失業率の下限",
    "MS=NGSHA_N+NGSHA_H+NGSHA_W+NDEPA_N+NDEPA_G+NDEPA_H+NDEPA_W": "朴(2026a)のMS定義",
    "LOG(IR_N)=#+#*LOG(IR_N(-1))+#*@PCH(YR)+#*RRL+#*DUM2009":
        "シナリオ8のアドファクター",
}

# 朴(2026) WP65 版で追加的に許す差。WP65 付録が「朴(2025c)からの変更点」として
# 明記している5本ぶん（WP65 付録 p.32-35、parkmodel.WP65_LINES）。
WP65_REMOVED = [
    "B2=#+#*YN+#*WB_N+#*TIME",
    "NL_CB=FINCOME_CB+GAPNL_CB",
    "NL_G=S_G-IN_G-NP_G+KTR_G+GAPNL_G",
    "NLBDA_N/ASSET_N=#+#*D(RRL)+#*RCHI+#*IN_N/ASSET_N+#*NEQUACG_N/ASSET_N"
    "+#*NLBDA_N(-1)/ASSET_N(-1)+#*NPENA_N(-1)/ASSET_N(-1)",
    "NPENA_N/ASSET_N=#+#*IN_N/ASSET_N+#*NEQUACG_N/ASSET_N+#*NPENA_N(-1)/ASSET_N(-1)",
]
WP65_ADDED = [
    "B2=YN-WB_N-TIN_N-SD",
    "NL_CB=GAPNL_CB",
    "NL_G=S_G-IN_G-NP_G+KTR_G+GAPNL_G+FINCOME_CB",
    "NLBDA_N/ASSET_N=#+#*RCHI+#*IN_N/ASSET_N+#*NEQUACG_N/ASSET_N"
    "+#*NLBDA_N(-1)/ASSET_N(-1)+#*NPENA_N(-1)/ASSET_N(-1)",
    "NPENA_N/ASSET_N=#+#*RCHI+#*RPSI+#*IN_N/ASSET_N+#*NLBDA_N(-1)/ASSET_N(-1)",
]


def skeleton(text):
    """数値係数を正規化する。識別子の数字とラグは保持する。"""
    out = []
    for line in text.split("\n"):
        s = line.split("'")[0].strip()
        if not s or "=" not in s:
            continue
        s = re.sub(r"\s+", "", s.upper())
        # 識別子と変数のラグを先に一つのトークンとして読む。
        s = re.sub(r"[A-Z_]\w*(?:\([+-]?\d+\))?|\d*\.?\d+(?:E[-+]?\d+)?",
                   lambda m: m[0] if re.match(r"[A-Z_]", m[0]) else "#", s)
        s = re.sub(r"[-+]#\*", "+#*", s)
        s = re.sub(r"=[-+]#", "=#", s)
        s = re.sub(r"\([-+]#", "(#", s)
        out.append(s)
    return out


def check_equations(text, wp65=False):
    """[0] 方程式が論文の原文から変わっていないかを見る。"""
    ok_rm = KNOWN_REMOVED + (WP65_REMOVED if wp65 else [])
    ok_ad = KNOWN_ADDED + (WP65_ADDED if wp65 else [])
    a = skeleton(io.open(PAPER_EQ, encoding="utf-8").read())
    b = skeleton(text)
    diff = [l for l in difflib.unified_diff(a, b, lineterm="", n=0)
            if l[:1] in "+-" and l[:3] not in ("---", "+++")]
    removed = [l[1:] for l in diff if l[0] == "-"]
    added = [l[1:] for l in diff if l[0] == "+"]
    bad = ([r for r in removed if r not in ok_rm]
           + [a_ for a_ in added if a_ not in ok_ad])
    # 既知差は置換の組で許す。片側の削除や重複追加だけは許さない。
    rm_counts, ad_counts = Counter(removed), Counter(added)
    for old, new in zip(ok_rm, ok_ad):
        if rm_counts[old] != ad_counts[new]:
            bad.append("既知の置換が対応していません: %s -> %s" % (old, new))
    print("[0] 方程式が論文から変わっていないか%s" % ("（WP65版）" if wp65 else ""))
    print("    式の本数         論文 %d / 使用 %d" % (len(a), len(b)))
    for r in removed:
        print("    論文にあって無い  %s" % r[:80])
    for a_ in added:
        print("    論文に無くて有る  %s" % a_[:80])
    if bad:
        print("    → 既知でない差がある。前向きの結果は論文のモデルのものではない。")
        for x in bad:
            print("       %s" % x[:90])
        return False
    # 実際に出た差だけを名前で挙げる。失業率の下限は既定では掛けないので、
    # unr_floor を渡したときだけここに出る。
    names, wp = [], 0
    for old, new in zip(ok_rm, ok_ad):
        if rm_counts[old] == 0:
            continue
        lab = KNOWN_LABEL.get(old)
        if lab is None:
            wp += 1
        elif lab not in names:
            names.append(lab)
    if wp:
        names.append("WP65の変更点%d本" % wp)
    print("    → 既知の差だけ（%s）。OK" % ("、".join(names) if names
                                          else "差なし。論文の式そのまま"))
    return True


def check_solved(m, d, horizon):
    """[1] 解けるか。実績期間から通しで解く。"""
    end = fc.LAST + horizon
    print("\n[1] 1997-%d年度を通しで解けるか" % end)
    try:
        sim = m.simulate(d, 1997, end, mode="dynamic", maxit=5000, tol=1e-7)
    except Exception as ex:
        print("    → 解けず: %s" % str(ex)[:100])
        return None
    print("    → 解けた（%d年間、うち前向き %d年）" % (end - 1997 + 1, horizon))
    return sim


def check_stock_flow(sim, horizon, tol_sum=3.0, tol_gov=3.0):
    """[2] ストックとフローの整合。

    純貸出の合計は本来ゼロ。実績でも統計上の不突合で数兆円ずれるので、
    前向きでその水準から大きく離れていないかを見る。
    政府は、純債務の増分が純貸出の符号を反転したものと一致するはず。
    評価調整をゼロにしてあるので、前向きではぴったり合うのが正しい。"""
    fut = range(fc.LAST + 1, fc.LAST + 1 + horizon)
    print("\n[2] ストックとフローの整合（兆円）")
    print("    %-6s %12s %14s" % ("年度", "純貸出の合計", "政府の増分の差"))
    ok = True
    for y in [fc.LAST - 4, fc.LAST] + list(fut):
        tot = sum(sim["NL_" + s].loc[y] for s in SECTORS) / 1000.0
        dn = (-sim["NGBA_G"].loc[y] + sim["NGBA_G"].loc[y - 1]) / 1000.0
        gap = dn - (-sim["NL_G"].loc[y] / 1000.0)
        mark = ""
        if y > fc.LAST:
            if abs(tot) > tol_sum or abs(gap) > tol_gov:
                mark, ok = "   ← 許容超え", False
        print("    %-6d %12.2f %14.2f%s" % (y, tot, gap, mark))
    print("    → %s" % ("整合している。OK" if ok else
                        "ずれている。外生の置き方かモデルの見直しが要る"))
    return ok


def check_drift(sim, horizon, keys=("YN", "YR", "PC", "W", "N_N", "KN_N")):
    """[3] 発散していないか。前向きの年率変化が実績期間の範囲に収まるか。"""
    fut = list(range(fc.LAST + 1, fc.LAST + 1 + horizon))
    print("\n[3] 発散していないか（年率変化率 ％）")
    print("    %-8s %18s %18s" % ("変数", "実績期間 1997-%d" % fc.LAST, "前向き"))
    ok = True
    for v in keys:
        h = sim[v].loc[1997:fc.LAST].pct_change().dropna() * 100
        f = sim[v].loc[fc.LAST:fut[-1]].pct_change().dropna() * 100
        lo, hi = h.min(), h.max()
        pad = max(2.0, (hi - lo) * 0.5)          # 実績の幅の半分ぶんは外を許す
        bad = (f.min() < lo - pad) or (f.max() > hi + pad)
        ok = ok and not bad
        print("    %-8s %8.2f 〜 %7.2f %8.2f 〜 %7.2f%s"
              % (v, lo, hi, f.min(), f.max(), "   ← 範囲外" if bad else ""))
    print("    → %s" % ("実績期間と同じくらいの動き。OK" if ok else
                        "実績期間より大きく振れている"))
    return ok


def check_plausible(sim, horizon):
    """[4] 値が経済的にありうる範囲か。"""
    fut = list(range(fc.LAST + 1, fc.LAST + 1 + horizon))
    f = sim.loc[fut]
    print("\n[4] 値が経済的にありうる範囲か")
    tests = [
        ("実質GDPが正",           (f["YR"] > 0).all()),
        ("消費デフレータが正",     (f["PC"] > 0).all()),
        ("失業率が0〜20％",        ((f["UNR"] > 0) & (f["UNR"] < 20)).all()),
        ("就業者数が労働力人口以下", (f["N_N"] <= f["LF"]).all()),
        ("名目賃金が正",           (f["W"] > 0).all()),
        ("資本ストックが正",       (f["KN_N"] > 0).all()),
    ]
    for name, res in tests:
        print("    %-24s %s" % (name, "OK" if res else "×"))
    floor = pm.UNR_FLOOR_DEFAULT
    if floor is None:
        print("    %-24s %s" % ("失業率の下限", "掛けていない（論文どおりの式）"))
    else:
        hit = int((f["UNR"] <= floor + 1e-9).sum())
        print("    %-24s %d / %d 年" % ("失業率が下限に張り付く", hit, len(fut)))
        if hit:
            print("       下限は論文に無い構造変更なので、張り付く年が多いほど")
            print("       結果は論文のモデルから離れる。既定は下限なしである。")
    return all(r for _, r in tests)


def main(argv):
    nums = [a for a in argv if a.lstrip("-").isdigit()]
    horizon = int(nums[0]) if nums else 10
    print("=" * 78)
    print("前向きシミュレーションの健全性チェック（%d-%d年度）"
          % (fc.LAST + 1, fc.LAST + horizon))
    print("=" * 78)

    # 解くモデルと、検証する方程式テキストは必ず同じものにする
    nominal = "hold" if "--hold" in argv else "gdp"
    wp65 = "--wp65" in argv
    m, d, text = fc.load(horizon=horizon, nominal=nominal, verbose=True, wp65=wp65)
    if not check_equations(text, wp65=wp65):
        print("\n方程式が論文から変わっているので、ここで止める。")
        return 1

    print("\n" + fc.describe(m.exog(), nominal))

    sim = check_solved(m, d, horizon)
    if sim is None:
        print("\n解けないこと自体が結果である。式をいじって解けるようにはしない。")
        return 1
    results = [check_stock_flow(sim, horizon),
               check_drift(sim, horizon),
               check_plausible(sim, horizon)]

    print("\n" + "=" * 78)
    print("すべて通過" if all(results) else "通らない項目がある（上を見ること）")
    print("=" * 78)
    print("""
【この結果は予測ではない】
  通ったのは「モデルが前向きに破綻しないか」であって、「当たるか」ではない。
  外生の大半を%d年度で据え置いているので、この経路は次を仮定している。

    ・労働力人口: %s
    ・実質の政府消費・政府投資が横ばい
    ・金利・為替・消費税率が変わらない
    ・株式や土地の値上がり益が今後いっさい発生しない

  見通しを作るならこれらを overrides で置き直すこと。朴(2025c) 自身は
  「難しい将来の外生変数の想定を避け」て前向きシミュレーションを行って
  いないので、ここから先の想定に論文の裏づけはない。""" % (fc.LAST,
        "社人研の将来推計人口 × 労働力率（%d年度で固定）" % fc.LAST
        if "LF" in fc.classify(m.exog())["将来推計"] else
        "%d年度の水準のまま（人口減を織り込んでいない）" % fc.LAST))
    sim.round(6).to_csv("park_forecast.csv", encoding="utf-8-sig")
    print("   park_forecast.csv に保存した")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
