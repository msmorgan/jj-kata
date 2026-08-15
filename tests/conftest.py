from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

TEST_CONFIG_HOME = Path(tempfile.mkdtemp(prefix="jj-kata-tests."))
os.environ["XDG_CONFIG_HOME"] = str(TEST_CONFIG_HOME)


def pytest_sessionfinish() -> None:
    shutil.rmtree(TEST_CONFIG_HOME, ignore_errors=True)
