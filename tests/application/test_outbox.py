import asyncio
from collections.abc import Awaitable, Callable

import pytest

from todoist_tui.application.mutation import Mutation, edit
from todoist_tui.application.outbox import Outbox
from todoist_tui.domain.priority import Priority


class Harness:
    """An `Outbox` with recording callbacks."""

    def __init__(self) -> None:
        self.resyncs = 0
        self.changes = 0
        self.errors: list[str] = []
        self.ran: list[str] = []
        self.rejected: list[str] = []
        self.on_resync: Callable[[], None] = lambda: None
        self.outbox = Outbox(
            resync=self._resync,
            on_change=self._changed,
            on_error=self.errors.append,
        )

    async def _resync(self) -> None:
        self.resyncs += 1
        self.on_resync()

    def _changed(self) -> None:
        self.changes += 1

    def queue(self, name: str) -> Mutation:
        """Queue a mutation whose command just records that it ran."""
        mutation = edit([name], priority=Priority.P1)

        async def command() -> None:
            self.ran.append(name)

        self.outbox.queue(mutation, command)
        return mutation

    def queue_failing(self, name: str, message: str) -> Mutation:
        mutation = edit([name], priority=Priority.P1)

        async def command() -> None:
            raise RuntimeError(message)

        self.outbox.queue(
            mutation, command, "Failed", lambda: self.rejected.append(name)
        )
        return mutation


async def _gated(gate: asyncio.Event) -> None:
    await gate.wait()


@pytest.mark.anyio
async def test_a_queued_mutation_is_pending_at_once() -> None:
    harness = Harness()

    mutation = harness.queue("a")

    assert harness.outbox.pending == (mutation,)
    assert harness.changes == 1
    await harness.outbox.idle()


@pytest.mark.anyio
async def test_commands_run_in_the_order_they_were_queued() -> None:
    harness = Harness()

    for name in ("a", "b", "c"):
        harness.queue(name)
    await harness.outbox.idle()

    assert harness.ran == ["a", "b", "c"]


@pytest.mark.anyio
async def test_a_burst_of_mutations_costs_one_resync() -> None:
    harness = Harness()

    for name in ("a", "b", "c"):
        harness.queue(name)
    await harness.outbox.idle()

    assert harness.resyncs == 1


@pytest.mark.anyio
async def test_a_command_with_no_mutation_still_runs_and_stays_out_of_pending() -> None:
    harness = Harness()

    async def command() -> None:
        harness.ran.append("bare")

    harness.outbox.queue(None, command)
    await harness.outbox.idle()

    assert (harness.ran, harness.outbox.pending) == (["bare"], ())


@pytest.mark.anyio
async def test_an_acknowledged_mutation_stays_pending_until_a_sync_lands() -> None:
    harness = Harness()

    harness.queue("a")
    await harness.outbox.idle()
    assert len(harness.outbox.pending) == 1  # acked, but unconfirmed by a snapshot

    async with harness.outbox.syncing():
        pass

    assert harness.outbox.pending == ()


@pytest.mark.anyio
async def test_a_sync_that_began_before_the_acknowledgement_does_not_retire() -> None:
    harness = Harness()
    ack = asyncio.Event()
    mutation = edit(["a"], priority=Priority.P1)
    harness.outbox.queue(mutation, lambda: _gated(ack))

    async with harness.outbox.syncing():  # its snapshot predates the command
        ack.set()
        await harness.outbox.idle()

    assert harness.outbox.pending == (mutation,)

    async with harness.outbox.syncing():  # this one began after the ack
        pass

    assert harness.outbox.pending == ()


@pytest.mark.anyio
async def test_a_failed_sync_retires_nothing() -> None:
    harness = Harness()
    harness.queue("a")
    await harness.outbox.idle()

    with pytest.raises(RuntimeError):
        async with harness.outbox.syncing():
            raise RuntimeError("offline")

    assert len(harness.outbox.pending) == 1


@pytest.mark.anyio
async def test_a_rejected_command_drops_only_its_own_mutation() -> None:
    harness = Harness()
    harness.queue_failing("a", "nope")
    kept = harness.queue("b")

    await harness.outbox.idle()

    assert harness.outbox.pending == (kept,)
    assert harness.ran == ["b"]  # the rest of the queue still ran
    assert harness.errors == ["Failed: nope"]  # the label leads the report


@pytest.mark.anyio
async def test_a_rejected_command_tells_its_caller() -> None:
    harness = Harness()
    harness.queue_failing("a", "nope")
    harness.queue("b")

    await harness.outbox.idle()

    assert harness.rejected == ["a"]


@pytest.mark.anyio
async def test_a_mutation_queued_during_the_drain_resync_still_runs() -> None:
    harness = Harness()

    def queue_b_mid_resync() -> None:
        if harness.resyncs == 1:  # the user acts while the resync is in flight
            harness.queue("b")

    harness.on_resync = queue_b_mid_resync

    harness.queue("a")
    await harness.outbox.idle()

    assert harness.ran == ["a", "b"]


@pytest.mark.anyio
async def test_retiring_reports_no_change() -> None:
    """The syncing caller draws the snapshot it fetched; a second paint to drop
    the replay on top of it would only repeat that frame."""
    harness = Harness()
    harness.queue("a")
    await harness.outbox.idle()
    changes = harness.changes

    async with harness.outbox.syncing():
        pass

    assert (harness.outbox.pending, harness.changes) == ((), changes)


@pytest.mark.anyio
async def test_a_queued_wave_goes_out_at_once() -> None:
    """Sent together, they reach the client in one turn, which posts them as one
    batch — Todoist runs a batch in order, so the user's sequence still holds."""
    harness = Harness()
    log: list[str] = []

    def recording(name: str) -> Callable[[], Awaitable[None]]:
        async def command() -> None:
            log.append(f"start {name}")
            await asyncio.sleep(0)
            log.append(f"end {name}")

        return command

    harness.outbox.queue(edit(["a"], priority=Priority.P1), recording("a"))
    harness.outbox.queue(edit(["b"], priority=Priority.P1), recording("b"))
    await harness.outbox.idle()

    assert log == ["start a", "start b", "end a", "end b"]
