"""Wait for an app's background workers to finish.

Textual types `App.workers` loosely, so the ignore the strict checker needs
lives here once instead of on every call site.
"""

from textual.app import App


async def settled[T](app: App[T]) -> None:
    await app.workers.wait_for_complete()  # pyright: ignore[reportUnknownMemberType]
