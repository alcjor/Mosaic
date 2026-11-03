import pytest
from mosaic_build.cli import main


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert "format 0.1" in capsys.readouterr().out


def test_unimplemented_commands_fail_loudly() -> None:
    assert main(["build"]) == 2
