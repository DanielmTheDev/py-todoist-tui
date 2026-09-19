import base64
import sys
from pathlib import Path

import pytest
from textual.widgets import Static

from todoist_tui.tui.imaging import (
    PREVIEW_ROWS,
    RENDERER_ENV,
    graphics_pane,
    text_pane,
)

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAQAAAACCAIAAADwyuo0AAAAEklEQVR4nGPkEpFjgAEmBiQAAAXaAED5u51GAAAAAElFTkSuQmCC"
)


def test_the_fallback_pane_names_the_file_it_cannot_draw() -> None:
    """Without a graphics-capable terminal the preview is still an answer, not a
    blank: it says which file is there."""
    pane = text_pane(Path("/cache/abc.png"), "shot.png")

    assert isinstance(pane, Static)
    assert "shot.png" in str(pane.content)


def test_a_missing_renderer_costs_the_preview_not_the_app(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The renderer is an ordinary dependency, but an install that predates it
    must still start — without one, comments simply read their file names."""
    monkeypatch.setitem(sys.modules, "textual_image.widget", None)

    assert graphics_pane() is text_pane


def test_the_drawn_image_is_given_a_height_to_fill(tmp_path: Path) -> None:
    """An image widget left on `auto` measures zero rows and draws nothing —
    the one failure that looks exactly like no image at all."""
    shot = tmp_path / "shot.png"
    shot.write_bytes(_PNG)

    pane = graphics_pane()(shot, "shot.png")

    assert pane.styles.height is not None
    assert pane.styles.height.value == PREVIEW_ROWS


def test_a_renderer_that_cannot_read_the_terminal_costs_only_the_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Choosing a renderer means probing the terminal, and that probe divides by
    a cell size the terminal may not report — under a bare pty it raises."""

    def explode(*_args: object, **_kwargs: object) -> object:
        raise ZeroDivisionError("division by zero")

    monkeypatch.setattr("textual_image._terminal.probe_terminal", explode)
    monkeypatch.delitem(sys.modules, "textual_image.widget", raising=False)
    monkeypatch.delitem(sys.modules, "textual_image.renderable", raising=False)

    assert graphics_pane() is text_pane


def test_the_renderer_can_be_named_when_the_terminal_is_misjudged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Auto-detection can pick a protocol the terminal advertises but bungles;
    naming one is the way out without editing code."""
    shot = tmp_path / "shot.png"
    shot.write_bytes(_PNG)
    monkeypatch.setenv(RENDERER_ENV, "halfcell")

    pane = graphics_pane()(shot, "shot.png")

    assert type(pane).__name__ == "HalfcellImage"


def test_an_unknown_renderer_name_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    shot = tmp_path / "shot.png"
    shot.write_bytes(_PNG)
    monkeypatch.setenv(RENDERER_ENV, "nonsense")

    assert graphics_pane()(shot, "shot.png") is not None
