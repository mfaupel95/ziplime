"""Missing liquidity must not turn a capped simulation into an unlimited fill.

Only synthetic in-memory frames are used. No exchange, bundle, configuration or
live trading runner is instantiated.
"""
import unittest

import numpy as np
import pandas as pd

from ziplime.finance.slippage.fixed_basis_points_slippage import FixedBasisPointsSlippage
from ziplime.vectorized.kernel import ExecutionTiming, ResolvedSlippage, simulate_signals


class MissingVolumeTests(unittest.TestCase):
    def simulate(self, volume, *, short=False, capped=True):
        index = pd.date_range("2024-01-02", periods=2, tz="UTC")
        prices = pd.DataFrame({"A": [10.0, 10.0]}, index=index)
        signals = pd.DataFrame({"A": [True, False]}, index=index)
        return simulate_signals(
            prices, entries=None if short else signals,
            short_entries=signals if short else None, allow_short=short,
            size=10.0, initial_cash=1000.0,
            execution=ExecutionTiming.same_close(),
            volumes=None if volume is None else pd.DataFrame(
                {"A": [volume, 100.0]}, index=index),
            slippage=FixedBasisPointsSlippage(basis_points=0, volume_limit=0.1)
            if capped else None,
        )

    def test_nan_volume_rejects_long_and_short_without_changing_cash(self):
        for short in (False, True):
            with self.subTest(short=short):
                result = self.simulate(np.nan, short=short)
                self.assertEqual(result.fills, [])
                self.assertEqual([r.reason for r in result.rejects], ["zero_size"])
                self.assertTrue((result.cash == 1000.0).all())
                self.assertTrue((result.positions == 0.0).all().all())

    def test_nonfinite_volume_has_no_capacity_in_both_paths(self):
        for volume in (np.nan, np.inf, -np.inf):
            with self.subTest(volume=volume):
                self.assertEqual(ResolvedSlippage(volume_limit=0.1).cap(10.0, volume), 0.0)
                self.assertEqual(self.simulate(volume).fills, [])

    def test_finite_positive_volume_still_caps_the_fill(self):
        result = self.simulate(20.0)
        self.assertEqual([f.amount for f in result.fills], [2.0])
        self.assertEqual(result.rejects, [])
        self.assertEqual(ResolvedSlippage(volume_limit=0.1).cap(10.0, 20.0), 2.0)

    def test_nonpositive_volume_still_rejects(self):
        for volume in (0.0, -20.0):
            with self.subTest(volume=volume):
                self.assertEqual(self.simulate(volume).fills, [])
                self.assertEqual(ResolvedSlippage(volume_limit=0.1).cap(10.0, volume), 0.0)

    def test_absent_volume_frame_and_uncapped_models_keep_their_contract(self):
        self.assertEqual([f.amount for f in self.simulate(None).fills], [10.0])
        self.assertEqual([f.amount for f in self.simulate(np.nan, capped=False).fills], [10.0])
        self.assertEqual(ResolvedSlippage(volume_limit=0.1).cap(10.0, None), 10.0)
        self.assertEqual(ResolvedSlippage().cap(10.0, np.nan), 10.0)


if __name__ == "__main__":
    unittest.main()
