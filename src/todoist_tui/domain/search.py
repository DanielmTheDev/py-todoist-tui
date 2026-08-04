from dataclasses import dataclass

# Todoist's filter grammar claims these; `search:` cannot quote them, so a term
# containing one is rejected by the API — and consecutive rejections escalate a
# retry penalty into the minutes. Cheaper to never send it.
_OPERATORS = "&|(),!"
_MIN_LENGTH = 2  # one character matches nearly everything, page after page


class InvalidSearchQuery(Exception):
    """Todoist rejected a query as malformed."""


@dataclass(frozen=True, slots=True)
class SearchTerm:
    """Free text Todoist can search for."""

    text: str

    @property
    def query(self) -> str:
        return f"search: {self.text}"

    def matches(self, content: str, description: str) -> bool:
        """Whether a task matches, judged as `search:` does — so the UI can tell
        locally that an edit it just made cannot have changed membership."""
        return (
            self.find_in(content) is not None or self.find_in(description) is not None
        )

    def find_in(self, text: str) -> tuple[int, int] | None:
        """Where the term first occurs in `text`, so a caller can point at it."""
        start = text.casefold().find(self.text.casefold())
        return None if start < 0 else (start, start + len(self.text))


@dataclass(frozen=True, slots=True)
class Unsearchable:
    """Why free text yields no query; `illegal` is empty when it's just too short."""

    illegal: str


def parse_search(text: str) -> SearchTerm | Unsearchable:
    """Read free text as a Todoist search, or say why it cannot be one.

    Inner whitespace and case survive verbatim: Todoist matches the term as a
    single case-insensitive substring, so "t est" would not find "test".
    """
    term = text.strip()
    if len(term) < _MIN_LENGTH:
        return Unsearchable("")
    illegal = dict.fromkeys(char for char in term if char in _OPERATORS)
    if illegal:
        return Unsearchable("".join(illegal))
    return SearchTerm(term)
