from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .errors import KataError


@dataclass(frozen=True)
class Result:
    stdout: str
    stderr: str
    returncode: int


class Jj:
    """Run jj in an explicit workspace directory, never through ``-R``."""

    def run(
        self,
        *args: str,
        cwd: Path,
        check: bool = True,
        show_stderr: bool = False,
    ) -> Result:
        process = subprocess.run(
            ["jj", "--no-pager", *map(str, args)],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )
        result = Result(process.stdout, process.stderr, process.returncode)
        if show_stderr and process.stderr:
            print(process.stderr, end="", file=__import__("sys").stderr)
        if check and process.returncode:
            detail = process.stderr.strip() or process.stdout.strip()
            raise KataError(detail or f"jj {' '.join(args)} failed")
        return result

    def text(self, *args: str, cwd: Path) -> str:
        return self.run(*args, cwd=cwd).stdout.strip()

    def lines(self, *args: str, cwd: Path) -> list[str]:
        return [line for line in self.text(*args, cwd=cwd).splitlines() if line]
