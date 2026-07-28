import datetime
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Due:
    """When a task is due. `time` is None for all-day (date-only) due dates."""

    date: datetime.date
    time: datetime.time | None = None
    is_recurring: bool = False
    # recurrence text, e.g. "every day"; kept so an update preserves the rule
    string: str | None = None
    lang: str | None = None

    @classmethod
    def from_api(cls, data: dict[str, object]) -> "Due":
        raw = data.get("datetime") or data.get("date")
        if not isinstance(raw, str):
            raise ValueError(f"due missing date/datetime: {data!r}")

        parsed = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
        has_time = "T" in raw
        string = data.get("string")
        lang = data.get("lang")
        return cls(
            date=parsed.date(),
            time=parsed.time() if has_time else None,
            is_recurring=bool(data.get("is_recurring", False)),
            string=string if isinstance(string, str) else None,
            lang=lang if isinstance(lang, str) else None,
        )

    @property
    def to_api(self) -> dict[str, str]:
        """Todoist Sync `due` object: date-only when all-day, else a datetime.

        A recurring due also carries its `string` (and `lang`) so an update
        moves the next occurrence without dropping the recurrence rule.
        """
        if self.time is None:
            payload = {"date": self.date.isoformat()}
        else:
            payload = {
                "datetime": datetime.datetime.combine(self.date, self.time).isoformat()
            }
        if self.is_recurring and self.string:
            payload["string"] = self.string
            if self.lang:
                payload["lang"] = self.lang
        return payload
