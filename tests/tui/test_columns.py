from rich.text import Text

from todoist_tui.tui.columns import GUTTER, TITLE_MIN, Column, fit_columns, fit_row


def _rows(*rows: list[str]) -> list[list[Text | str]]:
    return [[Text(cell) for cell in row] for row in rows]


def _labels(
    labels: list[str], rows: list[list[Text | str]], available: int
) -> list[str]:
    return [column.label for column in fit_columns(labels, rows, available, 0)]


def test_everything_fits_so_the_last_column_takes_the_slack() -> None:
    fitted = fit_columns(["TASK", "DUE"], _rows(["Buy milk", "Tue"]), 80, 0)

    assert [(c.label, c.index) for c in fitted] == [("TASK", 0), ("DUE", 1)]
    assert [c.width for c in fitted] == [8 + GUTTER, 80 - 8 - GUTTER]


def test_the_title_column_is_capped_before_any_column_is_dropped() -> None:
    title = "x" * 60
    fitted = fit_columns(["TASK", "DUE"], _rows([title, "Tue"]), 60, 0)

    assert [c.label for c in fitted] == ["TASK", "DUE"]
    assert fitted[0].width == 30  # half the table


def test_a_capped_title_never_goes_below_the_readable_minimum() -> None:
    title = "x" * 60
    fitted = fit_columns(["TASK", "DUE"], _rows([title, "Tue"]), 40, 0)

    assert fitted[0].width == TITLE_MIN


def test_columns_drop_least_useful_first() -> None:
    row = ["x" * 40, "@home", "Tue", "Wed", "Work"]
    labels = ["TASK", "LABELS", "DUE", "DEADLINE", "PROJECT"]

    assert _labels(labels, _rows(row), 60) == ["TASK", "LABELS", "DUE", "DEADLINE"]
    assert _labels(labels, _rows(row), 46) == ["TASK", "LABELS", "DUE"]
    assert _labels(labels, _rows(row), 36) == ["TASK", "DUE"]
    assert _labels(labels, _rows(row), 24) == ["TASK"]


def test_the_title_column_is_never_dropped() -> None:
    fitted = fit_columns(["TASK", "DUE"], _rows(["x" * 40, "Tue"]), 5, 0)

    assert [c.label for c in fitted] == ["TASK"]


def test_dropping_a_column_gives_the_title_its_full_width_back() -> None:
    """The cap is a last resort: once a drop frees the room, the title stops
    being truncated rather than staying at half the table."""
    fitted = fit_columns(
        ["TASK", "DUE", "PROJECT"],
        _rows(["x" * 38, "Tue", "y" * 28]),
        50,
        0,
    )

    assert [c.label for c in fitted] == ["TASK", "DUE"]
    assert fitted[0].width == 38 + GUTTER  # not the 25-cell cap


def test_no_layout_yet_leaves_the_natural_widths_alone() -> None:
    fitted = fit_columns(["TASK", "DUE"], _rows(["Buy milk", "Tue"]), 0, 0)

    assert [c.width for c in fitted] == [8 + GUTTER, 3 + GUTTER]


def test_the_title_column_clears_the_group_labels_when_there_is_room() -> None:
    fitted = fit_columns(["TASK", "DUE"], _rows(["Buy milk", "Tue"]), 80, 40)

    assert fitted[0].width == 40


def test_a_group_label_wider_than_the_cap_loses_to_it() -> None:
    fitted = fit_columns(["TASK", "DUE"], _rows(["Buy milk", "Tue"]), 40, 60)

    assert fitted[0].width == TITLE_MIN


def test_a_row_keeps_only_the_cells_of_the_columns_that_survived() -> None:
    cells: list[Text | str] = [Text("Buy milk"), Text("@home"), Text("Tue")]
    fitted = [Column(0, "TASK", 10), Column(2, "DUE", 5)]

    assert [str(cell) for cell in fit_row(cells, fitted)] == ["Buy milk", "Tue"]


def test_a_title_too_wide_for_its_column_is_ellipsized_clear_of_the_gutter() -> None:
    cells: list[Text | str] = [Text("Buy milk and bread"), Text("Tue")]
    fitted = [Column(0, "TASK", 10), Column(1, "DUE", 5)]

    title = str(fit_row(cells, fitted)[0])
    assert title == "Buy mil…"
    assert len(title) == 10 - GUTTER


def test_fitting_a_row_leaves_the_cells_it_was_given_alone() -> None:
    """Rows are rebuilt per render, but the same cell must not shrink twice if a
    caller ever reuses one."""
    cells: list[Text | str] = [Text("Buy milk and bread")]

    fit_row(cells, [Column(0, "TASK", 10)])

    assert str(cells[0]) == "Buy milk and bread"
