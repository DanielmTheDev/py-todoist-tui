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
        needle = self.text.casefold()
        return needle in content.casefold() or needle in description.casefold()


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
