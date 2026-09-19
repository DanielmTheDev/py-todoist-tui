from todoist_tui.domain.attachments import AttachmentFiles
from todoist_tui.domain.comment import Attachment
from todoist_tui.domain.links import LinkOpener


async def open_attachment(
    files: AttachmentFiles, opener: LinkOpener, attachment: Attachment
) -> None:
    """Show the file in whatever the desktop opens it with.

    The local copy is handed over rather than the URL: Todoist's file host
    answers an unauthenticated request with its login page, so a browser sent to
    the URL would show that instead of the file.
    """
    path = await files.local(attachment)
    opener.open(str(path))
