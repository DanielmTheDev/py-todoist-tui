import httpx

from todoist_tui.domain.attachments import (
    MAX_ATTACHMENT_BYTES,
    AttachmentTooLarge,
    NotTheFile,
)

# The file host, unlike the API, may answer slowly for a big image; and unlike a
# batched command, a download blocks nothing but its own preview.
_TIMEOUT_SECONDS = 60.0
_TODOIST_FILES = ".todoist.com"


class HttpAttachments:
    """Fetches a comment's file from wherever Todoist points at.

    A separate client from the API's: the token rides along only for Todoist's
    own hosts, so a comment linking a third party's file cannot collect it.
    """

    def __init__(self, http: httpx.AsyncClient, token: str) -> None:
        self._http = http
        self._token = token

    @classmethod
    def create(cls, token: str) -> "HttpAttachments":
        # the file URL redirects into object storage, so redirects are followed
        http = httpx.AsyncClient(timeout=_TIMEOUT_SECONDS, follow_redirects=True)
        return cls(http, token)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "HttpAttachments":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def fetch(self, url: str) -> bytes:
        headers = {"Authorization": f"Bearer {self._token}"} if _ours(url) else {}
        async with self._http.stream("GET", url, headers=headers) as response:
            response.raise_for_status()
            _refuse_a_page_instead_of_a_file(response)
            _refuse_a_declared_giant(response)
            return await _read_capped(response)


def _ours(url: str) -> bool:
    host = httpx.URL(url).host
    return host == "todoist.com" or host.endswith(_TODOIST_FILES)


def _refuse_a_page_instead_of_a_file(response: httpx.Response) -> None:
    # an unauthenticated fetch of a Todoist file answers 200 with the login page
    if response.headers.get("content-type", "").startswith("text/html"):
        raise NotTheFile(f"{response.url} answered with a web page, not the file")


def _refuse_a_declared_giant(response: httpx.Response) -> None:
    declared = response.headers.get("content-length")
    if declared is not None and int(declared) > MAX_ATTACHMENT_BYTES:
        raise AttachmentTooLarge(f"{declared} bytes")


async def _read_capped(response: httpx.Response) -> bytes:
    """Read the body, giving up past the cap — the length header is optional,
    and a wrong one must not be the only thing standing between us and it."""
    chunks: list[bytes] = []
    size = 0
    async for chunk in response.aiter_bytes():
        size += len(chunk)
        if size > MAX_ATTACHMENT_BYTES:
            raise AttachmentTooLarge(f"over {MAX_ATTACHMENT_BYTES} bytes")
        chunks.append(chunk)
    return b"".join(chunks)
