from __future__ import annotations

import os
import shutil
from pathlib import Path


def pytest_sessionfinish() -> None:
    shutil.rmtree(Path("/tmp") / f"jj-kata-tests-{os.getpid()}", ignore_errors=True)
