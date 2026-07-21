from pytest import CaptureFixture

from todoist_tui.__main__ import main


def test_main_returns_success_exit_code(capsys: CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert capsys.readouterr().out != ""
