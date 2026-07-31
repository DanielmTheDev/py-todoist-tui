import datetime
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Deadline:
    """The date a task must be done by. Todoist deadlines are date-only — no
    time-of-day and no recurrence, unlike a `Due`."""

    date: datetime.date

    @classmethod
    def from_api(cls, data: dict[str, object]) -> "Deadline":
        raw = data.get("date")
        if not isinstance(raw, str):
            raise ValueError(f"deadline missing date: {data!r}")
        return cls(date=datetime.date.fromisoformat(raw))

    @property
    def to_api(self) -> dict[str, str]:
        """Todoist Sync `deadline` object: a plain `YYYY-MM-DD` date."""
        return {"date": self.date.isoformat()}
