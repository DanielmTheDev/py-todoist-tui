import asyncio
import os
from pathlib import Path

from todoist_tui.domain.attachments import AttachmentSource, cache_name
from todoist_tui.domain.comment import Attachment


class CachedAttachments:
    """Keeps each attachment on disk under its content-addressed name, so a file
    is fetched once however often its comment is opened."""

    def __init__(self, directory: Path, source: AttachmentSource) -> None:
        self._directory = directory
        self._source = source

    async def local(self, attachment: Attachment) -> Path:
        path = self._directory / cache_name(attachment)
        if path.is_file():
            return path
        data = await self._source.fetch(attachment.file_url)
        await asyncio.to_thread(self._write, path, data)
        return path

    def _write(self, path: Path, data: bytes) -> None:
        """Write beside the target and move it into place: a download cut short
        would otherwise leave a stub that every later read trusts."""
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(f"{path.name}.part")
        partial.write_bytes(data)
        os.replace(partial, path)
