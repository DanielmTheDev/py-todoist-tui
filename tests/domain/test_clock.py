import datetime

from todoist_tui.domain.clock import SystemClock


def test_system_clock_returns_current_date() -> None:
    assert SystemClock().today() == datetime.date.today()
