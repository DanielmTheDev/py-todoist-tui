import datetime

from rich.text import Text

from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.tui.format import (
    format_deadline,
    format_due,
    render_links,
    styled_date,
)

_TODAY = datetime.date(2026, 8, 3)


def test_format_due_humanizes_date() -> None:
    assert format_due(Due(date=datetime.date(2026, 8, 4)), _TODAY) == "Tomorrow"


def test_format_due_appends_time() -> None:
    due = Due(date=_TODAY, time=datetime.time(14, 30))
    assert format_due(due, _TODAY) == "Today 14:30"


def test_format_due_blank_when_unset() -> None:
    assert format_due(None, _TODAY) == ""


def test_format_deadline_humanizes_date() -> None:
    assert (
        format_deadline(Deadline(date=datetime.date(2026, 8, 15)), _TODAY) == "15 Aug"
    )


def test_format_deadline_blank_when_unset() -> None:
    assert format_deadline(None, _TODAY) == ""


def test_styled_date_reds_overdue() -> None:
    result = styled_date("Yesterday", datetime.date(2026, 8, 2), _TODAY)
    assert result.plain == "Yesterday"
    assert result.style == "red"


def test_styled_date_plain_when_not_overdue() -> None:
    result = styled_date("Today", _TODAY, _TODAY)
    assert result.plain == "Today"
    assert result.style == ""


def _styled(text: Text, needle: str) -> str | None:
    """The style string of the span whose text is `needle`."""
    for span in text.spans:
        if text.plain[span.start : span.end] == needle:
            return str(span.style)
    return None


def test_markdown_alias_renders_label_only() -> None:
    result = render_links("[Check calendar](https://cal) today")

    assert result.plain == "Check calendar today"
    style = _styled(result, "Check calendar")
    assert style is not None
    assert "underline" in style
    assert "https://cal" in style  # OSC-8 link target


def test_bare_url_keeps_full_url_and_styles_it() -> None:
    result = render_links("see https://example.com/x. done")

    assert result.plain == "see https://example.com/x. done"  # trailing dot stays
    style = _styled(result, "https://example.com/x")
    assert style is not None
    assert "underline" in style


def test_plain_text_has_no_styled_spans() -> None:
    result = render_links("just a normal task")

    assert result.plain == "just a normal task"
    assert result.spans == []
