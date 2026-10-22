import datetime

from todoist_tui.domain.clock import SystemClock


def test_system_clock_returns_current_date() -> None:
    assert SystemClock().today() == datetime.date.today()


def test_system_clock_now_is_the_local_wall_clock() -> None:
    before = datetime.datetime.now()
    now = SystemClock().now()
    assert now.tzinfo is None  # floating, like Todoist's timed dues
    assert before <= now <= datetime.datetime.now()
