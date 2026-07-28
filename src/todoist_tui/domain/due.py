import datetime
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Due:
    """When a task is due. `time` is None for all-day (date-only) due dates."""

    date: datetime.date
    time: datetime.time | None = None
    is_recurring: bool = False

    @classmethod
    def from_api(cls, data: dict[str, object]) -> "Due":
        raw = data.get("datetime") or data.get("date")
        if not isinstance(raw, str):
            raise ValueError(f"due missing date/datetime: {data!r}")

        parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        has_time = "T" in raw
        return cls(
            date=parsed.date(),
            time=parsed.time() if has_time else None,
            is_recurring=bool(data.get("is_recurring", False)),
        )

    @property
    def to_api(self) -> dict[str, str]:
        """Todoist Sync `due` object: date-only when all-day, else a datetime."""
        if self.time is None:
            return {"date": self.date.isoformat()}
        return {"datetime": datetime.datetime.combine(self.date, self.time).isoformat()}
