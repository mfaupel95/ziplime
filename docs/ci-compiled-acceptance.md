# CI dependency repair and compiled acceptance

The failed GitHub Actions run 42605893416 stopped during installation, before
pytest: Poetry found no candidates for `polars-runtime-32==1.38.0` and reported
that `polars==1.38.0` was yanked. PyPI currently exposes a non-yanked 1.38.1
wrapper and matching runtime wheels, including CPython abi3 Linux x86_64.

The lock changes only these two packages to the immediately following patch
release 1.38.1, within the unchanged declared `polars = "^1.24.0"` constraint.
File names and SHA-256 hashes come directly from the PyPI 1.38.1 JSON metadata;
all other locked packages and the project content hash remain unchanged.
CI runs `poetry check --lock` and installs the full extras/dev set from that lock.
No dependencies were installed or system settings changed on the Windows host.

`python -m tests.vectorized.verify_numba_volume` requires the Numba extra, runs
all missing-volume cases against synthetic frames, and asserts the native
`run_events.nopython_signatures` collection is nonempty after execution. A
successful interpreted fallback is explicitly not an acceptance result.
The full pytest suite remains mandatory and unchanged after this native probe.
