import pytest
from textual.app import App

from todoist_tui.tui.screens.confirm import ConfirmScreen
from todoist_tui.tui.screens.scrolling import ScrollBody


class ConfirmApp(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.result: bool | None = None

    def open(self) -> None:
        self.push_screen(ConfirmScreen("Delete “x”?"), self._record)

    def _record(self, confirmed: bool | None) -> None:
        self.result = confirmed


@pytest.mark.anyio
async def test_y_confirms() -> None:
    app = ConfirmApp()
    async with app.run_test() as pilot:
        app.open()
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert app.result is True


@pytest.mark.anyio
async def test_escape_cancels() -> None:
    app = ConfirmApp()
    async with app.run_test() as pilot:
        app.open()
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.result is False


@pytest.mark.anyio
async def test_a_prompt_taller_than_the_terminal_scrolls() -> None:
    app = ConfirmApp()
    async with app.run_test(size=(80, 8)) as pilot:
        app.push_screen(ConfirmScreen("Delete " + "very long name " * 20 + "?"))
        await pilot.pause()

        body = app.screen.query_one(ScrollBody)
        assert body.region.bottom <= 8
        assert body.max_scroll_y > 0
