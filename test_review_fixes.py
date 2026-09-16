"""レビューで確認した失敗経路の回帰テスト。"""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd
import abenomics_park as ap
import parkmodel as pm
import reestimate as reest
import sanity_park as sp


class ReviewFixesTest(unittest.TestCase):
    def test_equation_guard_preserves_lags_and_identifiers(self):
        for wp65 in (False, True):
            text = pm.equations(version=1, coeffs='reest', wp65=wp65)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertTrue(sp.check_equations(text, wp65=wp65))
                for old, new in [('PM(-2)', 'PM(-1)'), ('DUM2009', 'DUM2020')]:
                    mutated = text.upper().replace(old, new)
                    self.assertNotEqual(mutated, text.upper())
                    self.assertFalse(sp.check_equations(mutated, wp65=wp65))
                self.assertTrue(ap.check_equations(wp65=wp65))
                without_ms = '\n'.join(line for line in text.splitlines()
                                       if not line.strip().upper().startswith('MS '))
                self.assertNotEqual(without_ms, text)
                self.assertFalse(sp.check_equations(without_ms, wp65=wp65))
        self.assertEqual(sp.skeleton('Y=1.234*X(-1)-2.345*DUM2009'),
                         sp.skeleton('Y=9.876*X(-1)+8.765*DUM2009'))

    def test_unconverged_calibration_is_not_returned(self):
        data = pd.DataFrame({'IR_N': [10000.], 'ADJ_IR_N': [0.]}, index=[2013])
        model = Mock()
        model.simulate.return_value = data
        with self.assertRaisesRegex(RuntimeError, '収束'):
            ap.calibrate_s8(model, data, data, maxit=1)
        # 成功時の残差は返す調整値に対するもの。
        model.simulate.return_value = data.assign(IR_N=5000.)
        adj, iterations, gap = ap.calibrate_s8(model, data, data, maxit=1)
        self.assertEqual((iterations, gap), (1, 0.))
        self.assertEqual(adj.iloc[0], 0.)

    def test_incomplete_scenarios_fail_before_publishing(self):
        with patch.object(ap, 'check_equations', return_value=True), \
             patch.object(ap, 'run_all', return_value=({'1. ベースライン': None}, [('s2', 'failed')])), \
             patch.object(pd.DataFrame, 'to_csv') as save, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ap.main(), 1)
            save.assert_not_called()

    def test_failed_estimation_preserves_both_outputs(self):
        for failed_result in (0, 1):
            with self.subTest(failed_result=failed_result), tempfile.TemporaryDirectory() as tmp:
                dst, wp = Path(tmp)/'base.eq', Path(tmp)/'wp.eq'
                dst.write_text('original base', encoding='utf-8')
                wp.write_text('original wp', encoding='utf-8')
                results = [(['new base'], []), (['new wp'], [])]
                results[failed_result][1].append('failed')
                with patch.object(reest, 'DST', str(dst)), patch.object(reest, 'DST_WP65', str(wp)), \
                     patch.object(reest, 'build', side_effect=results), patch.object(pm, 'data', return_value=None), \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(reest.main(), 1)
                self.assertEqual(dst.read_text('utf-8'), 'original base')
                self.assertEqual(wp.read_text('utf-8'), 'original wp')


    def test_hike_dummy_follows_the_tax_path(self):
        """2014年度の増税ダミーは、税率経路に 2014年度の引き上げがあるときだけ立つ。"""
        import contax_scenario as cs
        d = pd.DataFrame({'CONTAX': [5.0, 8.0]}, index=[2013, 2014])
        self.assertEqual(cs.hike_dummy(d), 1.0)          # 8%据え置き：5→8 の引き上げは残る
        d.loc[2014, 'CONTAX'] = 5.0
        self.assertEqual(cs.hike_dummy(d), 0.0)          # 5%据え置き：引き上げが無い


if __name__ == '__main__':
    unittest.main()
