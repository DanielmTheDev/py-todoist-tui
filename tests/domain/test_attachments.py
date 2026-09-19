from todoist_tui.domain.attachments import cache_name
from todoist_tui.domain.comment import Attachment


def _attachment(
    url: str = "https://files.todoist.com/x/shot.png", name: str = "shot.png"
) -> Attachment:
    return Attachment(file_name=name, file_type="image/png", file_url=url)


def test_the_same_file_always_lands_on_the_same_name() -> None:
    assert cache_name(_attachment()) == cache_name(_attachment())


def test_two_files_sharing_a_name_do_not_share_a_cache_entry() -> None:
    """Todoist gives attachments no id, so the name is addressed by URL —
    every second screenshot is called Screenshot.png."""
    first = cache_name(_attachment("https://files.todoist.com/a/Screenshot.png"))
    second = cache_name(_attachment("https://files.todoist.com/b/Screenshot.png"))

    assert first != second


def test_the_name_keeps_the_suffix_so_a_viewer_knows_the_type() -> None:
    assert cache_name(_attachment(name="shot.PNG")).endswith(".png")


def test_a_hostile_name_cannot_reach_out_of_the_cache_directory() -> None:
    hostile = _attachment(name="../../.bashrc")

    assert "/" not in cache_name(hostile)
    assert cache_name(hostile).endswith(".bin")


def test_an_unknown_suffix_falls_back_rather_than_being_trusted() -> None:
    assert cache_name(_attachment(name="notes")).endswith(".bin")
    assert cache_name(_attachment(name="report.pdf")).endswith(".pdf")
