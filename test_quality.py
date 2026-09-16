"""入力の取り違えと検証の偽成功を防ぐ回帰テスト。"""
import contextlib
import io
import tempfile
import os
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from sfcsim import Model
import park_test
import parkmodel as pm

class InputTest(unittest.TestCase):
    def test_invalid_options(self):
        for options in [
            {"mode": "statc"}, {"method": "newtn"},
            {"tol": 0}, {"tol": np.nan}, {"tol": np.inf},
            {"maxit": 0}, {"maxit": 1.5}, {"maxit": True},
            {"damp": 0}, {"damp": -1}, {"damp": 1.1}, {"damp": np.nan},
        ]:
            with self.subTest(options=options), self.assertRaises(ValueError):
                Model("Y=X").simulate(pd.DataFrame({"X": [1., 2.]}), 0, 1, **options)

    def test_invalid_axes_and_range(self):
        for data, start, end in [
            (pd.DataFrame({"X": [1., 2.]}, index=[0, 0]), 0, 0),
            (pd.DataFrame({"X": [1., 2.]}, index=[1, 0]), 0, 1),
            (pd.DataFrame([[1., 2.]], columns=["X", "X"]), 0, 0),
            (pd.DataFrame({"X": [1., 2.]}), 1, 0),
            (pd.DataFrame({"X": [1., 2.]}), 0, 2),
        ]:
            with self.subTest(data=data), self.assertRaises(ValueError):
                Model("Y=X").simulate(data, start, end)

    def test_modes_have_distinct_lag_behavior_and_preserve_input(self):
        data = pd.DataFrame({"Y": [1., 10., 100.]})
        before = data.copy()
        m = Model("Y = Y(-1) + 1")
        self.assertEqual(m.simulate(data, 1, 2, mode="static").at[2, "Y"], 11.)
        self.assertEqual(m.simulate(data, 1, 2, mode="dynamic").at[2, "Y"], 3.)
        pd.testing.assert_frame_equal(data, before)

class FinalValidationTest(unittest.TestCase):
    def test_success_solves_once_per_start(self):
        m = Model("Y = X")
        data = pd.DataFrame({"X": [1., 2., 3.]}, index=[2000, 2001, 2002])
        with patch.object(m, "simulate", wraps=m.simulate) as run:
            self.assertEqual(park_test.longest_final(m, data, (2000, 2001)),
                             [(2000, 2002, 3), (2001, 2002, 2)])
            self.assertEqual(run.call_count, 2)

    def test_failure_reports_last_solved_year(self):
        m = Model("Y = LOG(X)")
        data = pd.DataFrame({"X": [1., 2., -1.]}, index=[2000, 2001, 2002])
        with np.errstate(invalid="ignore"):
            self.assertEqual(park_test.longest_final(m, data, (2000,)),
                             [(2000, 2001, 2)])

    def test_main_rejects_incomplete_and_empty_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.chdir(tmp):
                # 最終年度より1年手前で止まった＝不完全。確報の版で変わるので
                # 直書きしない（2024年度版→2023年度版で落ちた）。
                short = pm.last_year() - 1
                for runs in ([(1997, short, short - 1997 + 1)],
                             [(1997, None, 0)], []):
                    with self.subTest(runs=runs), patch.object(park_test, "longest_final", return_value=runs):
                        with contextlib.redirect_stdout(io.StringIO()):
                            self.assertEqual(park_test.main(), 1)

if __name__ == "__main__":
    unittest.main()
