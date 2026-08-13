from __future__ import annotations

from pathlib import Path

import pytest

from jj_kata.config import find_config, load_config
from jj_kata.errors import KataError


@pytest.mark.parametrize("name", ["kata.toml", "jjkata.toml"])
def test_both_supported_config_names_resolve(tmp_path: Path, name: str) -> None:
    (tmp_path / name).write_text('[items]\nvisibility = "feature"\n')

    root, config = find_config(tmp_path / "nested")

    assert root == tmp_path
    assert config == {"items": {"visibility": "feature"}}


def test_two_supported_config_files_are_ambiguous(tmp_path: Path) -> None:
    (tmp_path / "kata.toml").write_text("")
    (tmp_path / "jjkata.toml").write_text("")

    with pytest.raises(KataError, match="both kata.toml and jjkata.toml exist"):
        load_config(tmp_path)
