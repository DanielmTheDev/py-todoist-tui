import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from todoist_tui.application.mutation import Mutation

type Command = Callable[[], Awaitable[None]]
type Spawn = Callable[[Coroutine[object, object, None]], None]


@dataclass(slots=True, eq=False)  # identity, so two like-for-like edits stay apart
class _Entry:
    mutation: Mutation | None  # None for a command with no effect on the rows
    command: Command
    label: str  # leads the message a rejection reports, e.g. "Failed to complete"
    on_reject: Callable[[], None] | None
    # syncs begun by the time the server acknowledged this command; None while it
    # is still queued or in flight. Only a sync begun *later* can confirm it.
    acked_after: int | None = field(default=None)


class Outbox:
    """The queue of local changes the server has not confirmed yet.

    Commands run one at a time, in the order the user issued them, so a rapid
    succession of actions can't reach Todoist out of order. Each mutation stays
    in `pending` — and so keeps being replayed over every reload — until a sync
    that *began after* its acknowledgement has landed. Confirming on a sync that
    was already in flight would apply a snapshot taken before the change and make
    the row flicker back; nothing further is needed, because Todoist is
    read-your-writes once a command is acknowledged.

    `resync` is awaited once the queue drains; it owns its own error handling.
    """

    def __init__(
        self,
        resync: Callable[[], Awaitable[None]],
        on_change: Callable[[], None],
        on_error: Callable[[str], None],
        spawn: Spawn | None = None,
    ) -> None:
        self._resync = resync
        self._on_change = on_change
        self._on_error = on_error
        self._spawn = spawn or self._spawn_task
        self._entries: list[_Entry] = []
        self._failures: list[str] = []  # reported once the resync has redrawn
        self._begun = 0  # syncs started so far, the clock acknowledgements read
        self._dispatching = False
        self._idle = asyncio.Event()
        self._idle.set()
        self._task: asyncio.Task[None] | None = None  # only to keep it from the GC

    @property
    def pending(self) -> tuple[Mutation, ...]:
        """The unconfirmed mutations, oldest first — replay them over a reload."""
        return tuple(e.mutation for e in self._entries if e.mutation is not None)

    def queue(
        self,
        mutation: Mutation | None,
        command: Command,
        label: str = "",
        on_reject: Callable[[], None] | None = None,
    ) -> None:
        """Take `mutation` as fact locally and send `command` behind it.

        `on_reject` runs if the server refuses the command — the caller's cue to
        forget whatever it staked on the change going through, such as its undo.
        """
        self._entries.append(_Entry(mutation, command, label, on_reject))
        self._on_change()
        if not self._dispatching:
            self._dispatching = True
            self._idle.clear()
            self._spawn(self._dispatch())

    async def idle(self) -> None:
        """Wait for the queue to drain and its resync to finish."""
        await self._idle.wait()

    @asynccontextmanager
    async def syncing(self) -> AsyncGenerator[None]:
        """Wrap a snapshot fetch: on a clean exit, everything the server had
        already acknowledged when it started is confirmed and retired."""
        token = self._begun
        self._begun += 1
        yield
        kept = [e for e in self._entries if not _confirmed_by(e, token)]
        if len(kept) != len(self._entries):
            self._entries = kept
            self._on_change()

    async def _dispatch(self) -> None:
        try:
            while True:
                entry = self._next_unsent()
                if entry is not None:
                    await self._send(entry)
                    continue
                await self._resync()
                self._report_failures()  # after the redraw, which would clobber them
                if self._next_unsent() is None:  # nothing queued while we synced
                    break
        finally:  # no await between the check above and here, so nothing strands
            self._dispatching = False
            self._idle.set()

    async def _send(self, entry: _Entry) -> None:
        try:
            await entry.command()
        except Exception as error:  # rejected: drop this change, keep the rest
            self._entries.remove(entry)
            if entry.on_reject is not None:
                entry.on_reject()
            self._failures.append(
                f"{entry.label}: {error}" if entry.label else str(error)
            )
            self._on_change()
        else:
            entry.acked_after = self._begun

    def _report_failures(self) -> None:
        if self._failures:  # the band holds one line, so the latest one speaks
            self._on_error(self._failures[-1])
            self._failures.clear()

    def _next_unsent(self) -> _Entry | None:
        return next((e for e in self._entries if e.acked_after is None), None)

    def _spawn_task(self, coroutine: Coroutine[object, object, None]) -> None:
        self._task = asyncio.create_task(coroutine)


def _confirmed_by(entry: _Entry, token: int) -> bool:
    return entry.acked_after is not None and entry.acked_after <= token
