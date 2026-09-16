"""グラフの日本語フォントを選ぶ。

matplotlib に候補リストをそのまま渡すと、見つからなかった候補ごとに
findfont の警告が出て、肝心の出力が埋もれてしまう（27年分の図で数千行）。
ここで実際に入っているものを1つだけ選んでから渡す。
"""

import matplotlib
from matplotlib import font_manager

# 上から順に探す。Windows / Mac / Linux の代表的な日本語フォント。
CANDIDATES = [
    "Yu Gothic",        # Windows
    "Meiryo",           # Windows（Yu Gothic が無い古い環境）
    "Hiragino Sans",    # Mac
    "Noto Sans CJK JP", # Linux（fonts-noto-cjk）
    "IPAexGothic",      # Linux（fonts-ipaexfont）
    "IPAPGothic",       # Linux（fonts-ipafont）
    "IPAGothic",        # Linux（fonts-ipafont / fonts-japanese-gothic）
    "TakaoGothic",      # Linux（fonts-takao）
    "VL Gothic",        # Linux（fonts-vlgothic）
    "WenQuanYi Zen Hei",  # Linux。中華圏向けだが日本語の字形も一通り持つ
]


def use_japanese_font():
    """入っている日本語フォントを matplotlib に設定し、その名前を返す。

    どれも入っていなければ何も設定せずに None を返す。その場合、図の
    日本語は豆腐（□）になるが、処理自体は止めない。
    """
    matplotlib.rcParams["axes.unicode_minus"] = False   # 軸のマイナス記号を化けさせない
    have = {f.name for f in font_manager.fontManager.ttflist}
    for name in CANDIDATES:
        if name in have:
            matplotlib.rcParams["font.family"] = name
            return name
    return None
