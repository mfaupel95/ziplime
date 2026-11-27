"""Exercise the same-run Ziplime wheel, never the checked-out package."""

import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
import venv

PEEWEE = "peewee-3.17.3.tar.gz"
PEEWEE_URL = (
    "https://files.pythonhosted.org/packages/7a/b1/"
    "2331e6b1fc8c61686dd9276f34142265462640eb0dd431246e30c4461065/" + PEEWEE
)
TEST = (
    "tests/assets/bonds/test_bond_end_to_end.py::BondOrderSizingTests"
    "::test_order_value_sizes_against_the_dirty_price"
)


def one(paths):
    path, = paths
    return path


def main(dist):
    root = Path(__file__).resolve().parents[2]
    wheel = one(dist.resolve().glob("ziplime-*.whl"))
    with wheel.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    print(f"{wheel.name} SHA256={digest}", flush=True)
    lock = tomllib.loads((root / "poetry.lock").read_text(encoding="utf-8"))
    peewee = one(p for p in lock["package"] if p["name"] == "peewee")
    expected = one(f["hash"] for f in peewee["files"] if f["file"] == PEEWEE)

    with tempfile.TemporaryDirectory(prefix="ziplime-wheel-") as tmp:
        scratch = Path(tmp)
        home = scratch / "home"
        home.mkdir()
        env = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR")}
        env.update({key: str(home) for key in
                    ("HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP")})
        env.update(PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PIP_CONFIG_FILE=os.devnull)
        venv.EnvBuilder(with_pip=True).create(scratch / "venv")
        python = scratch / "venv" / "Scripts" / "python.exe"

        def run(*args, cwd=scratch, extra_env=None):
            subprocess.run([python, "-I", "-B", *args], cwd=cwd,
                           env=env | (extra_env or {}), check=True)

        with urllib.request.urlopen(PEEWEE_URL, timeout=30) as response:
            source = response.read()
        if f"sha256:{hashlib.sha256(source).hexdigest()}" != expected:
            raise RuntimeError("Peewee sdist does not match poetry.lock")
        sdist = scratch / PEEWEE
        sdist.write_bytes(source)
        # Only this lockfile-verified sdist is allowed to build; omit optional C extensions.
        run("-m", "pip", "wheel", "--no-deps", "--index-url", "https://pypi.org/simple",
            "--wheel-dir", str(scratch), str(sdist), extra_env={"NO_SQLITE": "1"})
        run("-m", "pip", "install", "--only-binary=:all:", "--index-url",
            "https://pypi.org/simple", str(wheel), str(one(scratch.glob("peewee-*.whl"))),
            "pytest", "pytest-asyncio")
        run("-m", "pip", "check")
        run("-m", "ziplime", "--help")

        fixtures = scratch / "fixtures"
        shutil.copytree(root / "tests", fixtures / "tests")
        (fixtures / "data").mkdir()
        shutil.copy2(root / "data" / "assets.sqlite", fixtures / "data" / "assets.sqlite")
        run("-c", OFFLINE_TEST, TEST, cwd=fixtures)


OFFLINE_TEST = """\
import ipaddress
from pathlib import Path
import sys


def guard(event, args):
    if event == 'subprocess.Popen':
        raise RuntimeError('Subprocesses are disabled during the offline test')
    if event in ('socket.getaddrinfo', 'socket.connect', 'socket.sendto'):
        address = args[0] if event == 'socket.getaddrinfo' else args[1][0]
        try:
            loopback = ipaddress.ip_address(address).is_loopback
        except ValueError:
            loopback = False
        if not loopback:
            raise RuntimeError('External network is disabled during the offline test')


sys.addaudithook(guard)
sys.path.insert(0, str(Path.cwd()))
import pytest
import ziplime

package = Path(ziplime.__file__).resolve()
if not package.is_relative_to(Path(sys.prefix).resolve() / 'Lib' / 'site-packages'):
    raise RuntimeError(f'Expected the installed wheel, got {package}')
print(f'Testing installed package: {package}', flush=True)
raise SystemExit(pytest.main([
    '-v', '--tb=short', '-p', 'no:cacheprovider', '-p', 'pytest_asyncio.plugin',
    '-o', 'asyncio_default_fixture_loop_scope=function', sys.argv[1],
]))
"""


if __name__ == "__main__":
    main(Path(sys.argv[1]))
