# AGENTS.md — このリポジトリで作業するAIへの申し送り

朴勝俊（関西学院大学）の日本版 SFC マクロ計量モデル（方程式169本）を Python で
再実装したもの。**論文の方程式体系をそのまま解くこと**が唯一最大の目的で、
改良はすべて二の次。まず `README.md` を読むこと。

## 絶対に守ること

1. **方程式を論文から変えない。** 解けないときに式へ上限・下限・減衰項を足した瞬間に
   論文のモデルではなくなる。`python sanity_park.py` の [0] が、係数を潰した骨格を
   `paper/park2025c_model.eq` と突き合わせる。許される差は `sanity_park.py` の
   `KNOWN_*` / `WP65_*` に列挙してあり、**論文に明記された変更以外は足さない**
2. **解けないときはソルバーを直す。** `sfcsim` は発散した年を減衰を強めて解き直し、
   `Model.accept`（`parkmodel.accept_solution`）で定義の外の解（失業者数が負）を弾く。
   失業率に下限を置きたくなるが、それはモデルではなくソルバーの都合
3. **データの版は `fetch_ff.FY` の1か所で決まる**（2023年度確報。論文3本と同じ）。
   年度を直書きしない。版を変えると連鎖の参照年・遡及改定・統計表の組み方が変わる
4. **係数は `reestimate.py` が生成する。** `paper/*_reest.eq` を直接編集しない。
   `paper/park2025c_model.eq`（原文）は絶対に触らない
5. **論文にあることは論文で確認してから書く。** 推測で「論文はこう言っている」と書かない
6. **シミュレーションは全期間を通しで走らせる**（1997〜2023年度）。途中から始めると
   当てはまりが見かけ上よくなる
7. **反実仮想のベースラインは 2010年度起点**（WP65 4.1 節）。起点を動かすと政策効果の
   読みが変わる

## 数字を報告するときの作法

- 誤差率は論文の表11・表12・表20 と同じ期間・同じ定義で出す（`park_test.py`・
  `abenomics_park.py` が自動で並べる）
- データや係数を作り直したら、README・`guide.html` の数字も直し、
  `python abenomics_article.py` で記事を作り直す
- 拡張方向のショック（減税など）は失業率が低い領域に入るので、名目側の数字は
  割り引いて報告する（README「消費税を据え置いたら」）

## 動かし方

```bash
pip install -r requirements.txt
# データ（この順番。ESRI の Excel は cache/ に落ち、2回目以降はネットワーク不要）
python fetch_ff.py && python fetch_sector.py && python fetch_misc.py
python fetch_resid.py && python fetch_fincome.py && python fetch_endo.py
python reestimate.py
# 確認
python park_check.py && python park_test.py && python abenomics_park.py
python -m unittest test_sfcsim test_quality test_review_fixes test_fetch_ff test_fetch_misc
```

変更を入れたら、最低でも `park_check.py`・`park_test.py`・`abenomics_park.py` と
unittest を通すこと。

## 用語

| 語 | 意味 |
|---|---|
| パーシャルテスト | 各式の右辺に実績を入れて1回計算し、実績と比べる（論文 表11） |
| ファイナルテスト | 初期値だけ実績、あとはモデルの計算値で通しで解く（論文 表12） |
| バージョン1 / 2 | 論文冒頭のスイッチ。1 は金利固定（RrB 外生）、2 は金利内生。既定は 1 |
| WP65 版 | 朴(2026) WP65 が明記した5本の差し替えを入れた式体系 |
| 表20 | WP65 のシナリオ10（アベノミクス全効果）の結果表 |
