"""CI acceptance probe: fail rather than silently accepting the Python fallback."""
import unittest

from ziplime.vectorized.kernel import _core
from tests.vectorized.test_volume_cap_missing import MissingVolumeTests


def main():
    assert _core.HAVE_NUMBA, "The numba extra must be installed for this acceptance probe"
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(MissingVolumeTests)
    )
    assert result.wasSuccessful(), "Compiled missing-volume regressions failed"
    assert _core.run_events.nopython_signatures, "No native Numba signature executed"
    print("NUMBA_NATIVE_SIGNATURES:", _core.run_events.nopython_signatures)


if __name__ == "__main__":
    main()
