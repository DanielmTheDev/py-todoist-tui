import datetime

from rich.text import Text

from todoist_tui.domain.deadline import Deadline
from todoist_tui.domain.due import Due
from todoist_tui.domain.priority import Priority
from todoist_tui.tui.format import (
    MATCH_STYLE,
    format_deadline,
    format_due,
    format_labels,
    highlight_match,
    match_snippet,
    priority_dot,
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


def test_styled_date_dims_when_not_overdue() -> None:
    result = styled_date("Today", _TODAY, _TODAY)
    assert result.plain == "Today"
    assert result.style == "dim"


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


def test_format_labels_prefixes_and_joins() -> None:
    assert format_labels(("errand", "home")) == "@errand @home"


def test_format_labels_blank_when_empty() -> None:
    assert format_labels(()) == ""


def test_plain_text_has_no_styled_spans() -> None:
    result = render_links("just a normal task")

    assert result.plain == "just a normal task"
    assert result.spans == []


def test_priority_dot_marks_the_top_three() -> None:
    assert priority_dot(Priority.P1) == "🔴"
    assert priority_dot(Priority.P2) == "🟠"
    assert priority_dot(Priority.P3) == "🔵"


def test_priority_dot_leaves_the_default_blank() -> None:
    assert priority_dot(Priority.P4) == ""


def _accented(text: Text) -> list[tuple[str, str]]:
    return [(str(span.style), text.plain[span.start : span.end]) for span in text.spans]


def test_highlight_match_accents_only_the_matched_run() -> None:
    highlighted = highlight_match("Geschenk Manni", (0, 5))
    assert highlighted.plain == "Geschenk Manni"
    assert _accented(highlighted) == [(MATCH_STYLE, "Gesch")]


def test_highlight_match_without_a_match_is_unstyled() -> None:
    assert _accented(highlight_match("Martin Kremmel", None)) == []


def test_match_snippet_keeps_short_text_whole() -> None:
    snippet = match_snippet("buy a gift", (6, 10), width=40)
    assert snippet.plain == "buy a gift"


def test_match_snippet_windows_long_text_around_the_match() -> None:
    text = "a" * 60 + "gift" + "b" * 60
    snippet = match_snippet(text, (60, 64), width=20)
    assert "gift" in snippet.plain
    assert snippet.plain.startswith("…") and snippet.plain.endswith("…")
    assert len(snippet.plain) <= 22  # the window plus its two ellipses


def test_match_snippet_accents_the_match_after_windowing() -> None:
    text = "a" * 60 + "gift" + "b" * 60
    snippet = match_snippet(text, (60, 64), width=20)
    assert _accented(snippet) == [(MATCH_STYLE, "gift")]


def test_match_snippet_collapses_newlines() -> None:
    snippet = match_snippet("first line\nthe gift here", (15, 19), width=40)
    assert "\n" not in snippet.plain
