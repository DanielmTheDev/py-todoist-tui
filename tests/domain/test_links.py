from todoist_tui.domain.links import Link, annotate, attach, plain, sole_url


def test_markdown_link_becomes_label_with_marker() -> None:
    text, links = annotate("see [spec](https://example.com/spec) now", 1)

    assert text == "see spec [1] now"
    assert links == [Link(label="spec", url="https://example.com/spec")]


def test_bare_url_keeps_url_and_gets_marker() -> None:
    text, links = annotate("go https://tracker/T-42 today", 1)

    assert text == "go https://tracker/T-42 [1] today"
    assert links == [Link(label="https://tracker/T-42", url="https://tracker/T-42")]


def test_multiple_mixed_links_keep_order_and_number_sequentially() -> None:
    text, links = annotate("[a](http://x) then http://y and [b](http://z)", 1)

    assert text == "a [1] then http://y [2] and b [3]"
    assert [link.url for link in links] == ["http://x", "http://y", "http://z"]


def test_first_number_offsets_the_markers() -> None:
    text, links = annotate("[a](http://x)", 3)

    assert text == "a [3]"
    assert links == [Link(label="a", url="http://x")]


def test_links_past_the_last_number_lose_their_marker() -> None:
    text, links = annotate("[a](http://x) [b](http://y) [c](http://z)", 5, 6)

    assert text == "a [5] b [6] c"
    assert [link.url for link in links] == ["http://x", "http://y", "http://z"]


def test_no_last_number_numbers_every_link() -> None:
    text, _ = annotate("[a](http://x) [b](http://y)", 9)

    assert text == "a [9] b [10]"


def test_text_without_links_is_unchanged() -> None:
    text, links = annotate("just plain prose", 1)

    assert text == "just plain prose"
    assert links == []


def test_malformed_markdown_is_left_alone() -> None:
    text, links = annotate("broken [x]( link", 1)

    assert text == "broken [x]( link"
    assert links == []


def test_trailing_sentence_punctuation_is_not_part_of_the_url() -> None:
    text, links = annotate("read https://example.com/x. done", 1)

    assert text == "read https://example.com/x [1]. done"
    assert links == [Link(label="https://example.com/x", url="https://example.com/x")]


def test_url_wrapped_in_parens_keeps_the_closing_paren_as_text() -> None:
    text, links = annotate("(https://example.com/x)", 1)

    assert text == "(https://example.com/x [1])"
    assert links == [Link(label="https://example.com/x", url="https://example.com/x")]


def test_balanced_parens_inside_a_url_are_kept() -> None:
    url = "https://en.wikipedia.org/wiki/Example_(disambiguation)"

    bare, bare_links = annotate(url, 1)
    md, md_links = annotate(f"[wiki]({url})", 1)

    assert bare == f"{url} [1]"
    assert bare_links == [Link(label=url, url=url)]
    assert md == "wiki [1]"
    assert md_links == [Link(label="wiki", url=url)]


def test_plain_drops_bold_markers() -> None:
    assert plain("**Klaus-Peter Schicketanz**") == "Klaus-Peter Schicketanz"


def test_plain_drops_code_ticks() -> None:
    assert plain("run `uv sync` first") == "run uv sync first"


def test_plain_reduces_a_markdown_link_to_its_label() -> None:
    assert plain("see [the docs](https://example.com/x)") == "see the docs"


def test_plain_keeps_a_bare_url_whole() -> None:
    assert plain("see https://example.com/x now") == "see https://example.com/x now"


def test_plain_leaves_lone_asterisks_and_underscores_alone() -> None:
    # Todoist text legitimately contains these; only paired markers are markup
    assert plain("Birthdays _ Presents 2*3") == "Birthdays _ Presents 2*3"


def test_sole_url_recognises_a_pasted_url() -> None:
    assert sole_url("https://example.com/x") == "https://example.com/x"


def test_sole_url_ignores_whitespace_around_the_paste() -> None:
    assert sole_url("  https://example.com/x\n") == "https://example.com/x"


def test_sole_url_keeps_punctuation_a_deliberate_paste_carries() -> None:
    assert sole_url("https://example.com/x.") == "https://example.com/x."


def test_sole_url_rejects_a_url_among_other_words() -> None:
    assert sole_url("see https://example.com/x") is None


def test_sole_url_rejects_two_urls() -> None:
    assert sole_url("https://example.com/x https://example.com/y") is None


def test_sole_url_rejects_a_markdown_link() -> None:
    assert sole_url("[x](https://example.com/x)") is None


def test_sole_url_rejects_a_non_web_scheme() -> None:
    assert sole_url("ftp://example.com/x") is None


def test_attach_folds_the_url_into_a_plain_title() -> None:
    assert attach("review the PR", "http://x") == "[review the PR](http://x)"


def test_attach_appends_bare_when_there_is_no_label_to_use() -> None:
    assert attach("", "http://x") == "http://x"


def test_attach_appends_bare_when_the_title_already_carries_a_link() -> None:
    assert attach("[a](http://x)", "http://y") == "[a](http://x) http://y"
    assert attach("see http://x", "http://y") == "see http://x http://y"


def test_attach_appends_bare_when_a_bracket_would_break_the_label() -> None:
    assert attach("fix [42] crash", "http://x") == "fix [42] crash http://x"
