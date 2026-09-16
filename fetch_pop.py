"""fetch_pop.py -- 労働力人口(LF)の将来値を、社人研の将来推計人口から作る。

出力: japan_pop_proj_fy.csv （年度, LF）

やり方
  国立社会保障・人口問題研究所「日本の将来推計人口（令和5年推計）」の
  表1-1（総数・年齢3区分別人口、出生中位・死亡中位）から 15歳以上人口を取る。
  15歳以上人口 ＝ 総数 − 0〜14歳。

  労働力人口はこの推計には含まれないので、労働力率（労働力人口 ÷ 15歳以上人口）
  を実績最終年度の値で固定し、

      LF(t) = 15歳以上人口(t) × 労働力率(実績最終年度)

  として延ばす。つまり「人口構成の変化だけを織り込み、労働参加率は変わらない」
  という想定である。実際には高齢者と女性の労働参加率は上がってきており、
  この想定は労働力人口を低めに見積もる方向に働く。

  推計は暦年、モデルは年度なので、暦年 t を年度 t として扱う。人口は年央
  （10月1日）基準で、年度（4月〜翌3月）の中央は10月1日なので、ずれは小さい。

注意
  この延長は朴(2025c)(2026) の範囲外である。著者は前向きシミュレーションを
  行っておらず、労働力人口の将来値についての想定も示していない。
"""
import io
import os
import sys

import pandas as pd
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
URL = ("https://www.ipss.go.jp/pp-zenkoku/j/zenkoku2023/db_zenkoku2023/"
       "s_tables/1-1.xlsx")
CACHE = os.path.join(HERE, "cache", "ipss2023_1-1.xlsx")
DST = os.path.join(HERE, "japan_pop_proj_fy.csv")


def fetch_table():
    """表1-1 を取り、暦年 -> 15歳以上人口（万人）の Series にする。"""
    if os.path.exists(CACHE):
        raw = io.open(CACHE, "rb").read()
    else:
        r = requests.get(URL, timeout=120)
        r.raise_for_status()
        raw = r.content
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        io.open(CACHE, "wb").write(raw)
    d = pd.read_excel(io.BytesIO(raw), header=None)

    # 列は [和暦, 西暦, 総数, 0〜14歳, 15〜64歳, 65歳以上, ...]。西暦の列を探す。
    rows = {}
    for _, row in d.iterrows():
        try:
            year = int(row[1])
            total, young = float(row[2]), float(row[3])
        except (TypeError, ValueError):
            continue
        if not (1990 <= year <= 2130):
            continue
        rows[year] = (total - young) / 10.0        # 千人 -> 万人
    if len(rows) < 20:
        raise ValueError("表1-1 から人口を %d 年ぶんしか読めませんでした" % len(rows))
    s = pd.Series(rows).sort_index()
    s.index.name = "年度"
    return s


def main():
    print("=" * 74)
    print("労働力人口の将来値（社人研 日本の将来推計人口 令和5年推計）")
    print("=" * 74)
    pop15 = fetch_table()
    print("\n   15歳以上人口  %d〜%d年  %d年ぶん" % (pop15.index.min(), pop15.index.max(), len(pop15)))

    lf = pd.read_csv(os.path.join(HERE, "japan_misc_fy.csv"), index_col=0,
                     encoding="utf-8-sig")["LF"]
    lf.index = lf.index.astype(int)
    last = int(lf.index.max())
    if last not in pop15.index:
        raise ValueError("%d年が推計表にありません" % last)
    rate = float(lf.loc[last]) / float(pop15.loc[last])
    print("   実績の労働力人口 %d年度 %.0f万人" % (last, lf.loc[last]))
    print("   15歳以上人口     %d年   %.0f万人" % (last, pop15.loc[last]))
    print("   労働力率         %.4f（この率を将来も固定する）" % rate)

    fut = pop15.loc[last + 1:]
    out = pd.DataFrame({"LF": (fut * rate).round(2)})
    out.index.name = "年度"
    out.to_csv(DST, encoding="utf-8-sig")

    print("\n   %-6s %12s %12s" % ("年度", "15歳以上人口", "労働力人口"))
    for y in [last] + [y for y in (last + 1, last + 5, last + 10, last + 20,
                                   last + 30) if y in out.index]:
        p = pop15.loc[y]
        v = float(lf.loc[last]) if y == last else float(out["LF"].loc[y])
        print("   %-6d %12.0f %12.0f%s" % (y, p, v, "  ← 実績" if y == last else ""))
    n = len(out)
    print("\n   %s に保存した（%d年度〜%d年度、%d年ぶん）"
          % (os.path.basename(DST), out.index.min(), out.index.max(), n))
    print("=" * 74)
    return 0


if __name__ == "__main__":
    sys.exit(main())
