import asyncio
from collections.abc import Iterable

from todoist_tui.domain.attachments import AttachmentFiles
from todoist_tui.domain.clipboard import Clipboard
from todoist_tui.domain.comment import Attachment, Comment


async def copy_image(
    files: AttachmentFiles, clipboard: Clipboard, attachment: Attachment
) -> None:
    """Put the image on the clipboard. The local copy goes, not the URL: the
    file host answers an unauthenticated fetch with its login page."""
    path = await files.local(attachment)
    # xclip is shelled out to and can stall: off the event loop
    await asyncio.to_thread(clipboard.copy, path, attachment.file_type)


def newest_image(comments: Iterable[Comment]) -> Attachment | None:
    """The image most recently posted to a thread, in whatever order it came."""
    images = [c for c in comments if c.attachment and c.attachment.is_image]
    if not images:
        return None
    return max(images, key=lambda comment: comment.posted_at).attachment
