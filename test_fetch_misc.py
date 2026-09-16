"""test_fetch_misc.py -- 労働力調査 長期時系列表の読み込みの回帰テスト。

  python -m unittest test_fetch_misc

Excel は cache/ にあるものを使う（無ければ飛ばす）。列は見出しで探すので、
表の組み方が変わったときにここで気づけるようにしておく。"""
import os
import unittest
import warnings

import fetch_misc as fm

HAVE = os.path.exists(fm.LABOUR_CACHE)


@unittest.skipUnless(HAVE, "cache/ に長期時系列表の Excel が無い")
class LabourLongTermTableTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")      # openpyxl のヘッダ警告
            cls.d, cls.filled = fm.fetch_labour()

    def test_span_and_columns(self):
        d = self.d
        self.assertEqual(list(d.columns), ["LF", "EMP", "UN"])
        self.assertLessEqual(d.index.min(), 1994)
        self.assertGreaterEqual(d.index.max(), fm.FY)
        self.assertFalse(d.loc[1994:fm.FY].isna().any().any())

    def test_earthquake_years_are_present(self):
        # 2010〜2012年度は補完推計値が載っているので補間は要らない
        self.assertEqual(self.filled, [])
        self.assertTrue((self.d.loc[2010:2012, "LF"] > 6500).all())

    def test_1973_takes_row_including_okinawa(self):
        # 復帰前後の2行のうち、後の（沖縄を含む）行を採る
        self.assertEqual(int(self.d.loc[1973, "LF"]), 5323)

    def test_identity_and_known_values(self):
        d = self.d.loc[1994:fm.FY]
        self.assertLessEqual((d["EMP"] + d["UN"] - d["LF"]).abs().max(), 2.0)
        self.assertEqual(int(self.d.loc[1994, "LF"]), 6650)
        self.assertEqual(int(self.d.loc[2023, "UN"]), 178)


if __name__ == "__main__":
    unittest.main()


@unittest.skipUnless(os.path.exists(fm.HOURS_CACHE) and os.path.exists(fm.LOAD_CACHE),
                     "cache/ に毎勤の累積データか稼働率指数が無い")
class HoursAndLoadTest(unittest.TestCase):
    def test_hours_trend_matches_paper(self):
        # 30人以上の総実労働時間指数を TIME に回帰すると論文の W_HOURS の式と
        # 一致する（TIME = 年度 - 1993 の裏づけでもある）
        h = fm.fetch_hours()
        c0, c1 = fm.hours_trend(h, list(range(1994, 2024)))
        self.assertAlmostEqual(c0, fm.PAPER_WHMAX_C, delta=0.2)
        self.assertAlmostEqual(c1, fm.PAPER_WHMAX_T, delta=0.01)
        self.assertEqual(1994 - fm.TIME_ORIGIN, 1)

    def test_load_span_and_max(self):
        l = fm.fetch_load()
        self.assertLessEqual(l.index.min(), 1994)
        self.assertGreaterEqual(l.index.max(), fm.FY)
        # 1994年度以降の最大は 2007年度で、論文の LOADmax 135.6667 に近い
        self.assertEqual(int(l.loc[1994:fm.FY].idxmax()), 2007)
        self.assertAlmostEqual(float(l.loc[1994:fm.FY].max()), 135.67, delta=1.5)


@unittest.skipUnless(os.path.exists(fm.WEO_CACHE), "cache/ に IMF WEO の成長率が無い")
class WorldGdpTest(unittest.TestCase):
    def test_weo_vintage_and_index(self):
        g, src = fm._weo_world_growth()
        self.assertIn("2024-10", src)
        self.assertAlmostEqual(g[2023], 3.3, delta=0.15)     # WEO 2024年10月版の世界 2023年
        s = fm.fetch_world_gdp()
        self.assertAlmostEqual(float(s.loc[1994]), 100.0, places=6)
        self.assertGreater(float(s.loc[2023]), 250.0)
