"""ソルバーが異常な計算結果を正常終了として返さないことを確認する。"""
import unittest
import warnings
import numpy as np
import pandas as pd
from sfcsim import Model

class FiniteResultsTest(unittest.TestCase):
    def test_invalid_results_raise(self):
        cases = [
            ("Y = X", {"X": [np.nan]}),
            ("Y = X", {"X": [np.inf]}),
            ("Y = LOG(X)", {"X": [-1.0]}),
            ("LOG(Y) = X", {"X": [1000.0]}),
            ("Y = 0.5 * Y + X", {"X": [np.nan], "Y": [1.0]}),
        ]
        for method in ("gauss-seidel", "newton"):
            for equation, values in cases:
                with self.subTest(method=method, equation=equation, values=values):
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore", RuntimeWarning)
                        with self.assertRaisesRegex(RuntimeError, "Y"):
                            Model(equation).simulate(pd.DataFrame(values), 0, 0, method=method)

    def test_finite_solutions_still_work(self):
        for method in ("gauss-seidel", "newton"):
            for equation, expected in [("Y = X", 2.0), ("Y = 0.5 * Y + X", 4.0)]:
                with self.subTest(method=method, equation=equation):
                    result = Model(equation).simulate(pd.DataFrame({"X": [2.0]}), 0, 0, method=method)
                    self.assertAlmostEqual(result.at[0, "Y"], expected, places=7)

    def test_zero_division_is_retried_with_more_damping(self):
        """反復の途中で X=0 になるゼロ除算は、減衰を強めた解き直しで回復する。"""
        m = Model("X = 1/X - 1")
        result = m.simulate(pd.DataFrame({"X": [1.0]}), 0, 0)
        self.assertAlmostEqual(result.at[0, "X"], 0.618033989, places=6)

    def test_input_errors_are_not_retried(self):
        """変数の入れ忘れは入力の誤りなので、解き直さずそのまま上げる。"""
        with self.assertRaises(NameError):
            Model("Y = X + Z").simulate(pd.DataFrame({"X": [1.0]}), 0, 0)

    def test_invalid_difference_lag_raises(self):
        data = pd.DataFrame({"Y": [np.nan, 1.0], "X": [0.0, 1.0]})
        with self.assertRaisesRegex(RuntimeError, "Y"):
            Model("D(Y) = X").simulate(data, 1, 1)

if __name__ == "__main__":
    unittest.main()
