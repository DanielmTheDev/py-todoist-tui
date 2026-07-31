import datetime

from rich.text import Text

from todoist_tui.domain.deadline import Deadline
from todoist_tui.tui.format import format_deadline, render_links


def test_format_deadline_renders_iso_date() -> None:
    assert format_deadline(Deadline(date=datetime.date(2026, 8, 15))) == "2026-08-15"


def test_format_deadline_blank_when_unset() -> None:
    assert format_deadline(None) == ""


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
