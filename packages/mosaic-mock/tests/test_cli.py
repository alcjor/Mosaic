from __future__ import annotations

import json

import pytest
from mosaic_mock.cli import main


@pytest.mark.req("MOCK-15")
def test_scale_on_top_of_a_preset(tmp_path, capsys) -> None:
    out = tmp_path / "big"
    assert main(["generate", "--size", "small", "--scale", "2", "--out", str(out)]) == 0
    t = json.loads((out / "ground_truth.json").read_text())
    pcf = [i for i in t["items"] if i["type"] == "PCF"]
    assert len(pcf) == 160
    assert t["scale"] == 2.0
    assert "160" not in capsys.readouterr().err


def test_list_commands(capsys) -> None:
    assert main(["list-profiles"]) == 0
    assert "spacecraft" in capsys.readouterr().out
    assert main(["list-defects", "--profile", "spacecraft"]) == 0


def test_refuses_to_overwrite_a_foreign_folder(tmp_path) -> None:
    (tmp_path / "keep.txt").write_text("mine")
    with pytest.raises(FileExistsError):
        main(["generate", "--out", str(tmp_path)])


def test_unknown_size(tmp_path, capsys) -> None:
    assert main(["generate", "--size", "huge", "--out", str(tmp_path / "x")]) == 2
