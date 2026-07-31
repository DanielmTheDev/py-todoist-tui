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
        raw = data.get("date")  # `date` holds a datetime string when timed
        if not isinstance(raw, str):
            raise ValueError(f"due missing date: {data!r}")

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
        """Todoist Sync `due` object: the `date` field holds a plain date when
        all-day, else a floating ISO datetime (no tz) — Todoist has no separate
        `datetime` key and silently drops one, clearing the due.

        A recurring due also carries its `string` (and `lang`) so an update
        moves the next occurrence without dropping the recurrence rule.
        """
        if self.time is None:
            value = self.date.isoformat()
        else:
            value = datetime.datetime.combine(self.date, self.time).isoformat()
        payload = {"date": value}
        if self.is_recurring and self.string:
            payload["string"] = self.string
            if self.lang:
                payload["lang"] = self.lang
        return payload
