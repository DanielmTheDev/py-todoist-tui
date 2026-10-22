import datetime
from typing import Protocol


class Clock(Protocol):
    """Port to the wall clock; injected so `today`/`now` are deterministic in tests."""

    def today(self) -> datetime.date: ...

    def now(self) -> datetime.datetime: ...


class SystemClock:
    """System-local `today`/`now`. Assumes system TZ == Todoist account TZ (true for
    this single-user app); the `today` parity smoke test guards the assumption."""

    def today(self) -> datetime.date:
        return datetime.date.today()

    def now(self) -> datetime.datetime:
        return datetime.datetime.now()
