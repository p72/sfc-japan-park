"""資金循環の読み込みが、確報の版による表の組み方の違いを取り違えないことの回帰テスト。

2026-09-13 に、2023年度確報の「金融機関の内訳」表が資産側と負債側で別ファイルに
なっているのを見落とし、日銀の負債側に別の列を当てていたのが見つかった。
その再発を防ぐ。cache/ に確報の Excel が無い環境では飛ばす。"""
import os
import unittest

import pandas as pd

import fetch_ff as ff

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")


def _have(*names):
    return all(os.path.exists(os.path.join(CACHE, n)) for n in names)


class CentralBankColumnTest(unittest.TestCase):
    @unittest.skipUnless(_have("2023ss62_jp.xlsx", "2023ss63_jp.xlsx", "2023ss61_jp.xlsx"),
                         "2023年度確報の Excel が cache/ に無い")
    def test_2023_split_files(self):
        """2023年度確報：内訳表に「中央銀行」は1列。負債側は別ファイルが要る。"""
        s61 = os.path.join(CACHE, "2023ss61_jp.xlsx")
        s62 = os.path.join(CACHE, "2023ss62_jp.xlsx")
        s63 = os.path.join(CACHE, "2023ss63_jp.xlsx")
        sheet = pd.ExcelFile(s61).sheet_names[-1]
        self.assertEqual(len(ff._cb_columns(pd.read_excel(s62, sheet_name=sheet, header=None))), 1)
        with self.assertRaisesRegex(ValueError, "負債側"):
            ff.read_year(s61, s62, sheet)
        row = ff.read_year(s61, s62, sheet, s63)
        # 発行銀行券と日銀当座預金は日銀の負債なので、現金・HPM の純計は大きな負値
        self.assertLess(row["NGSHA_CB"], -500000.0)
        # 部門をまたぐ縦計（貨幣用金を除く）はゼロ
        for t in ff.TYPES:
            tot = sum(row["N%sA_%s" % (t, s)] for s in ff.SECTORS)
            if t == "GSH":
                continue
            self.assertAlmostEqual(tot, 0.0, places=3)

    @unittest.skipUnless(_have("2024ss62_jp.xlsx", "2024ss61_jp.xlsx"),
                         "2024年度確報の Excel が cache/ に無い")
    def test_2024_side_by_side(self):
        """2024年度確報：内訳表に「中央銀行」は資産側と負債側の2列。"""
        s61 = os.path.join(CACHE, "2024ss61_jp.xlsx")
        s62 = os.path.join(CACHE, "2024ss62_jp.xlsx")
        sheet = pd.ExcelFile(s61).sheet_names[-1]
        self.assertEqual(len(ff._cb_columns(pd.read_excel(s62, sheet_name=sheet, header=None))), 2)
        row = ff.read_year(s61, s62, sheet)
        self.assertLess(row["NGSHA_CB"], -500000.0)
        with self.assertRaisesRegex(ValueError, "負債側"):
            ff.read_year(s61, s62, sheet, s62)

    def test_check_rejects_missing_central_bank_liabilities(self):
        """日銀の負債側が落ちた残高（現金・HPM が小さい）を検算が弾く。"""
        idx = [2022, 2023]
        d = pd.DataFrame(index=idx)
        for t in ff.TYPES:
            for s in ff.SECTORS:
                d["N%sA_%s" % (t, s)] = 0.0
        d["NGSHA_H"] = 100000.0
        d["NGSHA_F"] = 500000.0
        d["NGSHA_CB"] = -1500.0                    # 取り違えていたときの大きさ
        for s in ff.SECTORS:
            d["NNFWA_%s" % s] = -sum(d["N%sA_%s" % (t, s)] for t in ff.TYPES)
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(ff.check(d, "残高"))
            d["NGSHA_CB"] = -600000.0
            d["NNFWA_CB"] = 600000.0
            self.assertTrue(ff.check(d, "残高"))


class SaveOnlyWhenCheckedTest(unittest.TestCase):
    def test_main_keeps_previous_csv_when_check_fails(self):
        """日銀の負債側が落ちた残高で main() を回しても、既存の CSV は書き換わらない。"""
        import contextlib, io, tempfile
        from unittest.mock import patch
        idx = [2022, 2023]
        stock = pd.DataFrame(index=idx)
        for t in ff.TYPES:
            for s in ff.SECTORS:
                stock["N%sA_%s" % (t, s)] = 0.0
        stock["NGSHA_H"], stock["NGSHA_F"], stock["NGSHA_CB"] = 100000.0, 500000.0, -1500.0
        for s in ff.SECTORS:
            stock["NNFWA_%s" % s] = -sum(stock["N%sA_%s" % (t, s)] for t in ff.TYPES)
        flow = stock * 0.0
        stock.index.name = flow.index.name = "年度"
        names = ["japan_ff_stock_fy.csv", "japan_ff_flow_fy.csv", "japan_ff_cg_fy.csv", "japan_ff_share_fy.csv"]
        with tempfile.TemporaryDirectory() as tmp, contextlib.chdir(tmp):
            for n in names:
                open(n, "w").write("previous")
            with patch.object(ff, "build", side_effect=[stock, flow]), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ff.main(), 1)
            for n in names:
                self.assertEqual(open(n).read(), "previous", n)


class PopulationProjectionTest(unittest.TestCase):
    def test_projection_must_start_the_year_after_last(self):
        """将来の労働力人口 CSV の始まりが実績の翌年度でなければ止まる。"""
        import contextlib, io, tempfile
        from unittest.mock import patch
        import forecast as fc
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "pop.csv")
            pd.DataFrame({"LF": [1.0, 2.0]}, index=pd.Index([fc.LAST + 2, fc.LAST + 3], name="年度")).to_csv(p, encoding="utf-8-sig")
            with patch.object(fc, "POP_PROJ", p), self.assertRaisesRegex(ValueError, "fetch_pop"):
                fc.pop_projection()
            pd.DataFrame({"LF": [1.0, 2.0]}, index=pd.Index([fc.LAST + 1, fc.LAST + 2], name="年度")).to_csv(p, encoding="utf-8-sig")
            with patch.object(fc, "POP_PROJ", p):
                self.assertEqual(int(fc.pop_projection().index.min()), fc.LAST + 1)


if __name__ == "__main__":
    unittest.main()
