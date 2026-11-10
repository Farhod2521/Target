"""Each process starts from its own module, in a fresh interpreter: an import
cycle hidden by the test session's import order stops a worker on deploy."""

import subprocess
import sys

import pytest


@pytest.mark.parametrize("module", ["app.worker", "app.main"])
def test_the_entrypoint_imports_on_its_own(module: str) -> None:
    run = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert run.returncode == 0, run.stderr[-2000:]
