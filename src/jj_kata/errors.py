from __future__ import annotations


class KataError(Exception):
    """An expected command refusal or failure."""

    def __init__(self, message: str, code: int = 1) -> None:
        super().__init__(message)
        self.code = code
