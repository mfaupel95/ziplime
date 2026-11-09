# Missing volume in the vector kernel

Kernel semantics version 1.0.1 treats a supplied non-finite volume capacity
(NaN or either infinity) as zero available capacity when a volume-limited
slippage model is active. The simulated intent is rejected with the existing
`zero_size` reason and volume-cap detail; cash and positions do not change.

Previously, NaN capacity bypassed both comparisons in the inner loop and
allowed the full requested amount to fill. Positive infinity also behaved as
unlimited capacity. The resolved Python slippage helper and the execution
loop now use the same finite-capacity rule.

This does not change the explicit no-volume-frame contract: `volumes=None`
means no capacity information, so it does not limit fills. A model without a
volume limit also continues to ignore volume values. Finite positive capacity
still clips fills; zero or negative capacity still permits no fill.

Regression checks use synthetic in-memory frames, without an exchange, data
bundle, configuration, live runner or external market data:

    python -B -m unittest tests.vectorized.test_vector_kernel tests.vectorized.test_volume_cap_missing -q

The optional Numba compiled path requires separate validation on an existing
Numba-enabled environment; no optional dependencies need installing for the
interpreted-path checks.
