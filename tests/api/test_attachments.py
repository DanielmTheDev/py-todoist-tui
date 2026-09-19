import httpx
import pytest
import respx

from todoist_tui.api.attachments import HttpAttachments
from todoist_tui.domain.attachments import (
    MAX_ATTACHMENT_BYTES,
    AttachmentTooLarge,
    NotTheFile,
)

_URL = "https://files.todoist.com/x/shot.png"
_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.mark.anyio
@respx.mock
async def test_a_todoist_file_is_fetched_with_the_token() -> None:
    route = respx.get(_URL).mock(
        return_value=httpx.Response(
            200, content=_PNG, headers={"content-type": "image/png"}
        )
    )
    async with HttpAttachments.create("tok") as files:
        assert await files.fetch(_URL) == _PNG

    assert route.calls.last.request.headers["Authorization"] == "Bearer tok"


@pytest.mark.anyio
@respx.mock
async def test_a_file_hosted_elsewhere_never_sees_the_token() -> None:
    """A comment may carry a link to a third party's file; the account's token
    is not theirs to receive."""
    route = respx.get("https://elsewhere.example/x.png").mock(
        return_value=httpx.Response(
            200, content=_PNG, headers={"content-type": "image/png"}
        )
    )
    async with HttpAttachments.create("tok") as files:
        await files.fetch("https://elsewhere.example/x.png")

    assert "Authorization" not in route.calls.last.request.headers


@pytest.mark.anyio
@respx.mock
async def test_a_login_page_is_refused_although_it_answers_200() -> None:
    """Todoist serves the sign-in page, with a 200, when the token is missing —
    the status says nothing, the content type does."""
    respx.get(_URL).mock(
        return_value=httpx.Response(
            200, content=b"<html>sign in</html>", headers={"content-type": "text/html"}
        )
    )
    async with HttpAttachments.create("tok") as files:
        with pytest.raises(NotTheFile):
            await files.fetch(_URL)


@pytest.mark.anyio
@respx.mock
async def test_a_file_that_declares_itself_too_big_is_not_read() -> None:
    respx.get(_URL).mock(
        return_value=httpx.Response(
            200,
            content=_PNG,
            headers={
                "content-type": "image/png",
                "content-length": str(MAX_ATTACHMENT_BYTES + 1),
            },
        )
    )
    async with HttpAttachments.create("tok") as files:
        with pytest.raises(AttachmentTooLarge):
            await files.fetch(_URL)


@pytest.mark.anyio
@respx.mock
async def test_a_file_that_keeps_coming_is_cut_off() -> None:
    """A missing or lying Content-Length must not let the stream run forever."""
    oversized = b"\x89PNG" + b"0" * (MAX_ATTACHMENT_BYTES + 1)
    respx.get(_URL).mock(
        return_value=httpx.Response(
            200, content=oversized, headers={"content-type": "image/png"}
        )
    )
    async with HttpAttachments.create("tok") as files:
        with pytest.raises(AttachmentTooLarge):
            await files.fetch(_URL)


@pytest.mark.anyio
@respx.mock
async def test_a_refusal_surfaces_as_an_http_error() -> None:
    respx.get(_URL).mock(return_value=httpx.Response(404))
    async with HttpAttachments.create("tok") as files:
        with pytest.raises(httpx.HTTPStatusError):
            await files.fetch(_URL)
