from tests.smoke.env import parse_env


def test_parses_key_value_lines() -> None:
    assert parse_env("TODOIST_SMOKE_TOKEN=abc123") == {"TODOIST_SMOKE_TOKEN": "abc123"}


def test_ignores_blanks_and_comments() -> None:
    text = "\n# a comment\n  \nKEY=value\n"
    assert parse_env(text) == {"KEY": "value"}


def test_strips_surrounding_quotes_and_whitespace() -> None:
    assert parse_env('KEY = "spaced token" ') == {"KEY": "spaced token"}


def test_keeps_equals_in_value() -> None:
    assert parse_env("KEY=a=b=c") == {"KEY": "a=b=c"}


def test_skips_lines_without_equals() -> None:
    assert parse_env("garbage line\nKEY=v") == {"KEY": "v"}
