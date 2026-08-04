import pytest

from todoist_tui.domain.search import SearchTerm, Unsearchable, parse_search


def test_term_wraps_text_in_todoist_search_operator() -> None:
    assert parse_search("milk") == SearchTerm("milk")
    assert SearchTerm("milk").query == "search: milk"


def test_surrounding_whitespace_is_stripped() -> None:
    # a trailing space would mint a second cache key and a duplicate request
    assert parse_search("  milk  ") == SearchTerm("milk")


def test_inner_whitespace_and_case_are_preserved() -> None:
    # Todoist treats the term as one substring: "t est" does not match "Test"
    assert parse_search("Test Task") == SearchTerm("Test Task")


def test_term_locates_its_match_case_insensitively() -> None:
    assert SearchTerm("gesch").find_in("Geschenk Manni") == (0, 5)


def test_term_locates_the_first_of_several_matches() -> None:
    assert SearchTerm("an").find_in("Manni Marco an") == (1, 3)


def test_term_locates_nothing_when_absent() -> None:
    assert SearchTerm("gesch").find_in("Martin Kremmel bjj") is None


def test_term_matches_a_title_case_insensitively() -> None:
    # mirrors what Todoist's `search:` does, so the UI can judge a row locally
    assert SearchTerm("milk").matches("Buy MILK", "")


def test_term_matches_a_description() -> None:
    assert SearchTerm("milk").matches("Groceries", "oat milk, 2x")


def test_term_matches_neither_field() -> None:
    assert not SearchTerm("milk").matches("Buy bread", "at the bakery")


@pytest.mark.parametrize("text", ["", "   ", "m", " m "])
def test_too_short_is_unsearchable_without_a_reason(text: str) -> None:
    assert parse_search(text) == Unsearchable("")


@pytest.mark.parametrize("char", ["&", "|", "(", ")", ",", "!"])
def test_filter_operators_are_rejected_unsent(char: str) -> None:
    # Todoist 400s on these inside `search:` and quoting does not escape them
    assert parse_search(f"ab{char}cd") == Unsearchable(char)


def test_every_rejected_character_is_reported_in_typed_order() -> None:
    assert parse_search("a&b|c") == Unsearchable("&|")


def test_repeated_rejected_character_is_reported_once() -> None:
    assert parse_search("a&b&c") == Unsearchable("&")


@pytest.mark.parametrize(
    "text",
    ["a@b", "a#b", "a%b", "a:b", "a-b", "don't", 'a"b', "a*b", "a?b", "tëst", "买菜"],
)
def test_characters_todoist_treats_as_literal_text_are_searchable(text: str) -> None:
    assert parse_search(text) == SearchTerm(text)
