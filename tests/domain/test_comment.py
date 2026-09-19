import datetime

import pytest

from todoist_tui.domain.comment import Attachment, Comment

_POSTED = "2026-09-18T19:04:11.000000Z"


def test_from_api_reads_a_plain_comment() -> None:
    comment = Comment.from_api(
        {"id": "c1", "item_id": "t1", "content": "looks good", "posted_at": _POSTED}
    )

    assert comment.id == "c1"
    assert comment.task_id == "t1"
    assert comment.content == "looks good"
    assert comment.posted_at == datetime.datetime(
        2026, 9, 18, 19, 4, 11, tzinfo=datetime.UTC
    )
    assert comment.attachment is None


def test_from_api_reads_an_image_attachment() -> None:
    comment = Comment.from_api(
        {
            "id": "c2",
            "item_id": "t1",
            "content": "",
            "posted_at": _POSTED,
            "file_attachment": {
                "file_name": "shot.png",
                "file_size": 2048,
                "file_type": "image/png",
                "file_url": "https://files.todoist.com/x/shot.png",
                "image": "https://files.todoist.com/x/shot.png",
                "image_width": 1200,
                "image_height": 800,
                "upload_state": "completed",
                "tn_m": ["https://image-resize.todoist.com/m", 288, 288],
            },
        }
    )

    attachment = comment.attachment
    assert attachment is not None
    assert attachment.file_name == "shot.png"
    assert attachment.file_size == 2048
    assert attachment.file_type == "image/png"
    assert attachment.file_url == "https://files.todoist.com/x/shot.png"
    assert attachment.image_width == 1200
    assert attachment.image_height == 800
    assert attachment.is_image
    assert attachment.thumbnail_url == "https://image-resize.todoist.com/m"


def test_an_attachment_that_is_not_an_image_says_so() -> None:
    """A PDF still lists and opens; only the preview is withheld."""
    attachment = Attachment.from_api(
        {
            "file_name": "spec.pdf",
            "file_type": "application/pdf",
            "file_url": "https://files.todoist.com/x/spec.pdf",
        }
    )

    assert not attachment.is_image
    assert attachment.thumbnail_url is None
    assert attachment.file_size == 0


def test_preview_url_falls_back_to_the_file_itself() -> None:
    """A freshly uploaded attachment carries no thumbnail yet, but the full
    image is already fetchable — previewing it beats showing nothing."""
    attachment = Attachment.from_api(
        {
            "file_name": "shot.png",
            "file_type": "image/png",
            "file_url": "https://files.todoist.com/x/shot.png",
        }
    )

    assert attachment.preview_url == "https://files.todoist.com/x/shot.png"


def test_preview_url_prefers_the_thumbnail() -> None:
    attachment = Attachment.from_api(
        {
            "file_name": "shot.png",
            "file_type": "image/png",
            "file_url": "https://files.todoist.com/x/shot.png",
            "tn_m": ["https://image-resize.todoist.com/m", 288, 288],
        }
    )

    assert attachment.preview_url == "https://image-resize.todoist.com/m"


def test_a_comment_without_an_id_is_refused() -> None:
    with pytest.raises(ValueError):
        Comment.from_api({"item_id": "t1", "content": "x", "posted_at": _POSTED})
