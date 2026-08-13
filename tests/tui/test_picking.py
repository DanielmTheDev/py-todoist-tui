from todoist_tui.tui.screens.picking import numbered, row_for_key


def test_numbered_prefixes_each_row_with_the_digit_that_picks_it() -> None:
    assert numbered(["Work", "Errands"]) == ["1 Work", "2 Errands"]


def test_numbered_indents_the_rows_past_nine_to_keep_the_labels_aligned() -> None:
    rows = numbered([f"p{i}" for i in range(11)])

    assert rows[8] == "9 p8"
    assert rows[9:] == ["  p9", "  p10"]  # only nine digits to hand out


def test_row_for_key_reads_the_index_a_digit_picks() -> None:
    assert row_for_key("1") == 0
    assert row_for_key("9") == 8


def test_row_for_key_ignores_every_other_key() -> None:
    assert row_for_key("0") is None  # nine rows, so zero picks nothing
    assert row_for_key("a") is None
    assert row_for_key("enter") is None
    assert row_for_key("") is None  # substring of the key list, but not a key
