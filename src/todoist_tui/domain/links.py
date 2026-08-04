import re
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol

# Markdown [label](url) first, so a URL inside one is never rematched as bare.
# The markdown destination allows one level of balanced parens (e.g. Wikipedia
# "…Example_(disambiguation)"); a bare URL grabs to whitespace and is trimmed.
_LINK = re.compile(
    r"\[(?P<label>[^\]]+)\]\((?P<mdurl>[^\s()]+(?:\([^\s()]*\)[^\s()]*)*)\)"
    r"|(?P<url>https?://\S+)"
)
_TRAILING = "].,;:!?\"'"  # sentence punctuation that clings to a bare URL
# only *paired* markers are markup: a lone * or _ is ordinary Todoist text
_EMPHASIS = re.compile(r"\*\*(?P<bold>[^*]+)\*\*|`(?P<code>[^`]+)`")


def _trim(url: str) -> str:
    """Drop trailing punctuation the writer meant as prose, not URL. A closing
    paren stays only when the URL opened one itself."""
    while url:
        if url[-1] == ")" and url.count("(") >= url.count(")"):
            break
        if url[-1] not in _TRAILING and url[-1] != ")":
            break
        url = url[:-1]
    return url


@dataclass(frozen=True, slots=True)
class Link:
    label: str  # markdown label, or the URL itself for a bare link
    url: str


def parse(text: str) -> Iterator[tuple[str, Link | None, str]]:
    """Walk `text` yielding (plain_before, link_or_None, trailing) per link, then
    a final (tail, None, "") chunk. `trailing` is punctuation trimmed off a bare
    URL that belongs to the prose, not the link."""
    pos = 0
    for match in _LINK.finditer(text):
        if match.group("label") is not None:
            link, trailing = Link(match.group("label"), match.group("mdurl")), ""
        else:
            grabbed = match.group("url")
            url = _trim(grabbed)
            link, trailing = Link(url, url), grabbed[len(url) :]
        yield text[pos : match.start()], link, trailing
        pos = match.end()
    yield text[pos:], None, ""


def plain(text: str) -> str:
    """Todoist text as the writer meant it to read: links reduced to their label,
    paired `**bold**` and `` `code` `` markers dropped."""
    unlinked = "".join(
        before + (link.label if link is not None else "") + trailing
        for before, link, trailing in parse(text)
    )
    return _EMPHASIS.sub(lambda m: m.group("bold") or m.group("code"), unlinked)


def annotate(text: str, first_number: int) -> tuple[str, list[Link]]:
    """Rewrite each link to 'display [n]' and collect the links in order.

    Markdown `[label](url)` renders as `label [n]`; a bare URL keeps its text.
    Numbering runs sequentially from `first_number`, so callers can thread it
    across several blocks (title then description)."""
    links: list[Link] = []
    out: list[str] = []
    for before, link, trailing in parse(text):
        out.append(before)
        if link is None:
            continue
        links.append(link)
        out.append(f"{link.label} [{first_number + len(links) - 1}]{trailing}")
    return "".join(out), links


class LinkOpener(Protocol):
    """Port to the system URL handler; injected so tests never launch a browser."""

    def open(self, url: str) -> None: ...


class XdgOpenLinkOpener:
    """Hand the URL to `xdg-open`, detached and silenced so the browser launch
    never writes over the TUI."""

    def open(self, url: str) -> None:
        subprocess.Popen(
            ["xdg-open", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
