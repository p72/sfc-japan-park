"""parkmodel.py -- 朴(2025c) の方程式体系とデータを読み込む。

論文のモデルには冒頭にスイッチがあり、2つのバージョンを切り替える。

  バージョン1（金利固定）  実質国債金利 RrB は外生。日銀の国債保有 NGBA_CB が
                          残余として決まる。論文6章のシミュレーションと、
                          WP65 の反実仮想はこちら。WP65 は RrB を政策変数として
                          動かしているので、外生でなければならない。
  バージョン2（金利内生）  NGBA_CB を外生とし、国債市場を均衡させるように
                          RrB = RrB(-1) - 1e+7 * NGBA_SUM で RrB を調整する。
                          論文7章はこちら。

公表されている方程式体系はバージョン2の状態で貼り付けられている。バージョン2の
調整式は係数が 1e+7 と極端に大きく、Gauss-Seidel でも Newton でも解けなかった。
EViews は解けているようだが、ここでは既定をバージョン1にしておく。

使い方:
    import parkmodel as pm
    m, d = pm.load()                 # バージョン1
    sim = m.simulate(d, 1997, pm.last_year(), mode="static")
"""
import os
import re

import pandas as pd

from sfcsim import Model

HERE = os.path.dirname(os.path.abspath(__file__))
EQ = os.path.join(HERE, "paper", "park2025c_model.eq")
EQ_REEST = os.path.join(HERE, "paper", "park2025c_model_reest.eq")
EQ_WP65_REEST = os.path.join(HERE, "paper", "park2026wp65_model_reest.eq")

DATA_FILES = ["japan_ff_stock_fy.csv", "japan_ff_flow_fy.csv", "japan_ff_cg_fy.csv",
              "japan_ff_share_fy.csv", "japan_sector_fy.csv", "japan_misc_fy.csv",
              "japan_resid_fy.csv", "japan_fincome_fy.csv", "japan_endo_fy.csv"]

_RRB_LINE = "RrB = RrB(-1) - 1e+7 * NGBA_SUM"
_NGBA_CB_LINE = "'NGBA_CB  =  - ( NGBA_N  + NGBA_F  + NGBA_G  + NGBA_H  + NGBA_W )"


# 失業率の下限。既定は None ＝ 論文どおりの UNR = UN/LF*100 をそのまま解く。
#
# 下限を置きたくなるのは、賃金式の 2.414/UNR で Gauss-Seidel が行きすぎて発散する
# ためだが、発散はモデルではなくソルバーの都合である。sfcsim が発散した年を減衰を
# 強めて解き直すので、下限なしで全シナリオが解ける。拡張方向の消費税据え置きでも失業率は 1.07% までしか下がらず、
# 負にはならない。論文からの構造的な逸脱は無い。
# 下限を掛けて感応度を見たいときは unr_floor=UNR_FLOOR_SAFE のように明示する。
UNR_FLOOR_DEFAULT = None
UNR_FLOOR_SAFE = 2.0         # ％。戦後日本の完全失業率の最小は1.1%前後


# 海外部門(W)のポートフォリオ式の正誤表。
#
# 朴(2025c)/(2026a) は、海外部門の3本について本文 p.40 と巻末モデルコードで
# 別々の係数を載せている。巻末のほうが古い推定で、本文 p.40 の式が著者の
# 実際に使ったものである。根拠は、論文自身が報告する誤差率をどちらが再現するか。
#
#   変数        論文の報告   巻末コード   本文 p.40
#   NSA_W       14.53%      14.15%      14.25%   ← 本文が近い
#   NLBDA_W      3.06%       4.17%       3.23%   ← 本文が近い
#
# 表14（推定結果）も巻末と同じ古い値を載せているので、本文の式だけが新しい。
# 3本目の NEQUA_W は巻末でも推定式がコメントアウトされ残差式が有効なので、
# ここでは触らない（本文も「株式は残余項として推計値を求めた」としている）。
#
# 差し替えるのは coeffs="paper" のときだけ。既定の coeffs="reest" では
# この2本とも再推定するので関係がない。
_W_ERRATA = {
    "NSA_W": ("NSA_W = NNFWA_W * ( 0.0385616031094 + 0.875608908424 * "
              "NSA_W(-1) / NNFWA_W(-1))",
              "NSA_W = NNFWA_W * (0.04289116526 + 0.847712159031 * "
              "NSA_W(-1) / NNFWA_W(-1))"),
    "NLBDA_W": ("NLBDA_W = NNFWA_W * ( - 0.85933310691 + 2.22960485647 * (RL - I_US)"
                " - 0.26163379119 * D(NEER) + 0.34806892821 * NEER"
                " - 1.38678017386 * NEQUACG_W / NNFWA_W"
                " - 0.485842960709 * NSA_W(-1) / NNFWA_W(-1)"
                " + 0.634596115343 * NLBDA_W(-1) / NNFWA_W(-1))",
                "NLBDA_W = NNFWA_W * (-0.73506034834 + 1.29318349452 * (RL - I_US)"
                " - 0.218941113427 * D(NEER) + 0.21446831313 * NEER"
                " - 1.33716192688 * NEQUACG_W / NNFWA_W"
                " - 0.382262186671 * NSA_W(-1) / NNFWA_W(-1)"
                " + 0.641957077292 * NLBDA_W(-1) / NNFWA_W(-1))"),
}


# マネーストックの定義。巻末のモデルコードは海外部門(W)を含む古い式だが、
# 朴(2026a) 5節は「通貨保有主体（法人部門と家計部門に、地方自治体等を加えた
# ものであり、海外部門は含まれない）」として、次の式を明記している。
#
#   MS = NGSHA_N + NGSHA_H + NDEPA_N + NDEPA_G + NDEPA_H
#
# 政府が日銀に置く預金（NGSHA_G）は政府預金なので除き、政府が民間銀行に
# 置く預金（NDEPA_G）は地方自治体等の預金として含める、という整理である。
# 日銀のM3の概念に合わせた修正なので、こちらを無条件に採る。MS はどの式の
# 右辺にも出てこない報告用の変数なので、他への波及はない。
# 実績側の MS も同じ定義で作ってある（fetch_endo.py 参照）。
_MS_2026A = ("ms = ngsha_n + ngsha_h + ngsha_w + ndepa_n + ndepa_g + ndepa_h + ndepa_w",
             "ms = ngsha_n + ngsha_h + ndepa_n + ndepa_g + ndepa_h")


# 朴(2026) WP65 付録が「朴(2025c)からの主な変更点」として明記した式の差し替え。
# 出典は WP65 付録 p.33。
#
#  (1)(2) 日銀の黒字を全額いっぺんに一般政府へ移す。朴(2025c)/(2026a) は
#         「モデル内では政府への納付金を分析には含めない」としていた。
#  (3)    営業余剰 B2 を回帰式から残余計算式に変える。SD は統計上の不突合で、
#         YFn = Yn - TIN_N - SD, B2 = YFn - WB_N という国民経済計算の関係から
#         来る。SD は外生として与える（fetch_endo.py 参照）。
#  (4)(5) 非金融法人のポートフォリオ式を 2006-2023 で推計し直したものに
#         差し替える。説明変数の顔ぶれ自体が変わっているので、係数を推定し
#         直すだけでは届かない。下に書いてあるのは論文が載せた係数で、
#         coeffs="reest" のときは reestimate.py がこの形のまま推定し直す。
#
# NEQUA_N は朴(2025c) と同じく＜不使用＞で、残差式 NEQUA_N = -ASSET_N -
# NLBDA_N - NPENA_N のほうが生きているため、ここでは触らない。
WP65_LINES = [
    ("NL_CB", "NL_CB = GAPNL_CB"),
    ("NL_G", "NL_G = S_G - In_G - NP_G + KTR_G + GAPNL_G + FINCOME_CB"),
    ("B2", "B2 = Yn - WB_N - TIN_N - SD"),
    ("NLBDA_N / ASSET_N",
     "NLBDA_N / ASSET_N = 0.275886632303 - 1.93414298244 * RCHI"
     " - 2.71336436925 * IN_N / ASSET_N"
     " - 0.157152366275 * NEQUACG_N / ASSET_N"
     " + 1.24463102032 * NLBDA_N(-1) / ASSET_N(-1)"
     " - 4.28481316364 * NPENA_N(-1) / ASSET_N(-1)"),
    ("NPENA_N / ASSET_N",
     "NPENA_N / ASSET_N = 0.108642635667 - 0.695147935268 * RCHI"
     " + 0.599156279009 * RPSI"
     " - 0.900820992904 * IN_N / ASSET_N"
     " + 0.117455239675 * NLBDA_N(-1) / ASSET_N(-1)"),
]


def _swap_line(text, lhs, new_line):
    """左辺が lhs である式の行を、まるごと new_line に差し替える。

    係数が原文と再推定版で違うので、行の中身ではなく左辺で狙う。
    コメント行（' 始まり）は対象にしない。"""
    key = re.sub(r"\s+", "", lhs).upper()
    hit = []
    for i, line in enumerate(text.split("\n")):
        s = line.strip()
        if not s or s.startswith("'") or "=" not in s:
            continue
        if re.sub(r"\s+", "", s.split("=")[0]).upper() == key:
            hit.append(i)
    if len(hit) != 1:
        raise ValueError("左辺 %s の式が %d 本です" % (lhs, len(hit)))
    lines = text.split("\n")
    lines[hit[0]] = new_line
    return "\n".join(lines)


def apply_wp65(text):
    """朴(2026) WP65 の変更点を適用する。"""
    for lhs, new_line in WP65_LINES:
        text = _swap_line(text, lhs, new_line)
    return text


def equations(version=1, coeffs="reest", unr_floor=None, w_errata=True,
              wp65=False):
    """方程式体系のテキストを返す。

    version は 1 か 2。coeffs は "reest"（こちらのデータで推定し直した係数）
    または "paper"（論文の係数のまま）。論文の係数は著者のデータセットの上で
    推定されたもので、こちらのデータには移せない。事情は
    paper/plan_a_original_coefficients.md を参照。"""
    if wp65:
        src = EQ_WP65_REEST if coeffs == "reest" else EQ
    else:
        src = EQ_REEST if coeffs == "reest" else EQ
    text = open(src, encoding="utf-8").read()
    if text.count(_MS_2026A[0]) != 1:
        raise ValueError("マネーストックの式が想定と違います")
    text = text.replace(*_MS_2026A)
    if wp65 and coeffs != "reest":
        text = apply_wp65(text)
    if coeffs == "paper" and w_errata:
        # 巻末に残った古い係数を、本文 p.40 のものに差し替える（_W_ERRATA 参照）
        for v, (stale, fixed) in _W_ERRATA.items():
            if text.count(stale) != 1:
                raise ValueError("%s の巻末の式が想定と違います" % v)
            text = text.replace(stale, fixed)
    if version == 2:
        return text
    if _RRB_LINE not in text or _NGBA_CB_LINE not in text:
        raise ValueError("スイッチの行が見つかりません。抽出結果が変わった可能性があります。")
    if unr_floor is not None:
        # 失業率は UNR = (LF - N_N)/LF*100 という差し引きで決まるので、就業者数が
        # 数％ずれると負になりうる。負の失業率は経済的にありえないうえ、賃金式に
        # 2.414/UNR の形で入るためモデル全体が壊れる。摩擦的失業ぶんの下限を置く。
        # UNR_FLOOR は外生変数として与える。
        old = [l for l in text.split("\n") if re.match(r"^\s*UNR\s*=", l, re.I)]
        if len(old) != 1:
            raise ValueError("UNR の式が1本ではありません（%d本）" % len(old))
        text = text.replace(old[0], "UNR = MAX(UN / LF * 100, UNR_FLOOR)")
    text = text.replace(_RRB_LINE, "' " + _RRB_LINE)          # RrB を外生に戻す
    # NGBA_CB のスイッチ行は原文に2箇所ある（冒頭と日銀の節）。同じ式なので
    # 片方だけ有効にする。両方戻すと同じ内生変数に式が2本あることになる。
    if text.count(_NGBA_CB_LINE) != 2:
        raise ValueError("NGBA_CB のスイッチ行が想定と違います（%d 箇所）"
                         % text.count(_NGBA_CB_LINE))
    text = text.replace(_NGBA_CB_LINE, _NGBA_CB_LINE[1:], 1)   # NGBA_CB を内生にする
    return text


def accept_solution(cur):
    """1時点ぶんの解を受け入れてよいか。

    賃金式の 2.414/UNR があるため、この体系は同じ年に複数の解を持つことが
    ある。実際 1997年度から通しで解くと、減衰なしの Gauss-Seidel は2007年度で
    失業率 -1.83% という解に落ちる（就業者数が労働力人口を超える）。そこから
    先は 2.414/UNR の符号が反転して、賃金の当てはまりが崩れる。

    失業者数 UN は人数なので負にはなれない。モデルの定義の外にある解なので、
    ここで弾く。弾かれた年は sfcsim が減衰を強めて解き直し、失業率 +1.17% の
    ほうの解に行く。**式には一切手を入れていない**（AGENTS.md の1番目）。
    失業率に下限を置いていたのは、もともとこの解を踏まないためだった。
    """
    for v in ("UN", "UNR"):
        x = cur.get(v)
        if x is not None and x <= 0.0:
            return False
    return True


def model(version=1, coeffs="reest", unr_floor=None, name=None, w_errata=True,
          wp65=False):
    m = Model(equations(version, coeffs, unr_floor, w_errata, wp65),
              name=name or "park%s_v%d_%s" % ("2026wp65" if wp65 else "2025c",
                                              version, coeffs),
              fold_case=True)
    m.accept = accept_solution
    return m


def wp65_residuals(d):
    """朴(2026) WP65 の日銀まわりの変更に合わせて、純貸出の調整項を組み直す。

    GAPNL_CB と GAPNL_G は、資本勘定から計算した純貸出と金融勘定の純貸出との
    差を埋めるデータセット側の残差である（本体 4.1・4.2、fetch_resid.py と
    fetch_fincome.py）。式の形を変えたら、残差の定義もそれに合わせないと、
    実績を再現しなくなってしまう。

      朴(2025c)  NL_CB = FINCOME_CB + GAPNL_CB   GAPNL_CB = NL_CB(実績) - FINCOME_CB
                 NL_G  = ... + GAPNL_G           GAPNL_G  = NL_G(実績) - (...)
      朴(2026)   NL_CB = GAPNL_CB                GAPNL_CB = NL_CB(実績)
                 NL_G  = ... + GAPNL_G + FINCOME_CB
                                                 GAPNL_G  = 上の GAPNL_G - FINCOME_CB

    こうしておくと、ベースラインではどちらも実績どおりの NL_CB・NL_G を出す。
    変わるのは伝わり方だけである。すなわち、利下げなどで日銀の金融純所得
    FINCOME_CB が動いたとき、朴(2025c) ではそれが日銀に留まったのに対し、
    朴(2026) では全額が政府の純貸出に入る。反実仮想ではここが効く。

    WP65 が「各年度の日銀の純貸出はゼロとする」と書いているのは、日銀の
    純貸出が実績でも名目GDPの0.5%未満（-1.3兆〜+2.5兆円）で、金融純所得
    （4〜6兆円）を全額政府に渡した残りはほぼゼロだ、という意味に読める。
    """
    d = d.copy()
    d["GAPNL_G"] = d["GAPNL_G"] - d["FINCOME_CB"]
    d["GAPNL_CB"] = d["NL_CB"]
    return d


def data():
    """作成済みの CSV を1枚に束ねる。列名は大文字に揃える。"""
    out = None
    for f in DATA_FILES:
        x = pd.read_csv(os.path.join(HERE, f), index_col=0, encoding="utf-8-sig")
        x.columns = [c.upper() for c in x.columns]
        # 整数だけの列（労働力人口など）は int64 で読まれ、モデルが小数を代入した
        # ときに pandas が型を理由に止まる。数値はすべて float にそろえる
        x = x.astype(float)
        if out is None:
            out = x
        else:
            out = out.join(x[[c for c in x.columns if c not in out.columns]], how="outer")
    out = out.sort_index()
    out.index.name = "年度"
    return out


def last_year():
    """データセットの最終年度。

    国民経済計算の確報の版（`fetch_ff.FY`）で決まる。ここを直書きしないのは、
    版を上げ下げしたときにコードとデータがずれるのを防ぐためである。
    朴論文は 2023年度国民経済計算を使っており、こちらも同じ版に揃えてある。"""
    x = pd.read_csv(os.path.join(HERE, DATA_FILES[0]), index_col=0,
                    encoding="utf-8-sig")
    return int(x.index.max())


def deflator_base():
    """デフレータの基準年（指数が1になる年度）。

    確報の版で変わる。2023年度確報は2015年度、2024年度確報は2020年度である。
    図の軸ラベルに直書きすると、版を変えたときに嘘になる。"""
    pc = data()["PC"]
    return int((pc - 1.0).abs().idxmin())


def load(version=1, coeffs="reest", unr_floor=UNR_FLOOR_DEFAULT, wp65=False):
    """既定は論文どおりの式。unr_floor=2.0 のように渡すと失業率に下限を置く。

    wp65=True で 朴(2026) WP65 の変更点を入れた式体系になる（WP65_LINES 参照）。"""
    d = data()
    if wp65:
        d = wp65_residuals(d)
    if unr_floor is not None:
        d["UNR_FLOOR"] = unr_floor
    return model(version, coeffs, unr_floor, wp65=wp65), d
