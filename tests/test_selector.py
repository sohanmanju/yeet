"""Tests for the shared deletion selector."""

from datetime import datetime
from pathlib import Path

from yeet.ui.selector import DeletionItemSelector
from yeet.utils import LeftoverItem


def test_selector_renders_leftover_items_without_extension():
    item = LeftoverItem(
        path=Path("/tmp/Slack"),
        name="Slack",
        source="Application Support",
        size=1024,
        last_modified=datetime.now(),
        app_hint="Slack Helper",
    )

    selector = DeletionItemSelector([item], title="App Leftovers")

    row_text = "".join(fragment[1] for fragment in selector._get_row(0))

    assert "Slack" in row_text
    assert "Slack Helper" in row_text
