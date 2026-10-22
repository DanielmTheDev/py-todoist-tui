import datetime


class FakeClock:
    """A wall clock frozen at `today`, 14:27."""

    def __init__(self, today: datetime.date) -> None:
        self._today = today

    def today(self) -> datetime.date:
        return self._today

    def now(self) -> datetime.datetime:
        return datetime.datetime.combine(self._today, datetime.time(14, 27))
