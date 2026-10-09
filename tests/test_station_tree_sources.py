"""Tests for the multi-source StationTree Sources section and fanout logic.

wx-dependent rendering is exercised through the pure-logic seams: the
tree's source-row bookkeeping methods and the panel's fanout merge, both
driven with stub objects so no wx event loop is needed.
"""

from unittest import mock

import pytest

wx = pytest.importorskip("wx")

from radiomaster.services.sources import SourceNode, StationRef
from radiomaster.services.sources.base import SourceUnavailable
from radiomaster.ui.widgets.station_tree import (
    SECTION_SOURCES,
    StationTree,
)


@pytest.fixture
def tree():
    """A StationTree against a stub StationDB, in the Sources section."""
    app = wx.App(False)
    frame = wx.Frame(None)
    db = mock.Mock()
    db.station_count.return_value = 0
    panel = StationTree(frame, db)
    panel.show_sources([("SomaFM", "somafm"), ("ACB Media", "acb_media")])
    yield panel
    panel.Destroy()
    frame.Destroy()
    app.Destroy()


def _node(label="A channel", playable=True, note=""):
    station = StationRef(name=label, url="https://example/stream",
                         source_id="somafm") if playable else None
    return SourceNode(label=label, path="p", station=station, note=note)


def test_show_sources_lists_enabled_sources(tree):
    labels = [name for name, _count in tree._current_groups]
    assert labels == ["SomaFM", "ACB Media"]
    assert tree._source_ids == ["somafm", "acb_media"]
    assert tree._current_section == SECTION_SOURCES


def test_source_rows_render(tree):
    rows = [_node("Groove Salad"), _node("Boot Liquor")]
    tree.set_source_rows("somafm", rows)
    assert tree._current_source_rows == rows


def test_source_failure_renders_sentence_not_silence(tree):
    tree.set_source_failed("somafm", "SomaFM could not be reached. Try again.")
    # The failure is a single unplayable row -- never a silent empty list.
    assert tree._source_nodes["somafm"] == ["SomaFM could not be reached. Try again."]


def test_selected_station_is_none_in_sources_section(tree):
    # A stale Station from a previous section must not leak through the
    # Sources section's selection.
    assert tree.get_selected_station() is None


def test_get_selected_source_row(tree):
    rows = [_node("One"), _node("Two")]
    tree.set_source_rows("somafm", rows)
    tree.station_list.Select(1)
    assert tree.get_selected_source_row().label == "Two"


def test_selecting_source_triggers_browse_callback(tree):
    calls = []
    tree.on_source_selected = calls.append
    tree._select_group_index(1)
    assert calls == ["acb_media"]


def test_cached_source_renders_without_second_browse(tree):
    calls = []
    tree.on_source_selected = calls.append
    tree.set_source_rows("somafm", [_node("Cached")])
    tree._select_group_index(0)
    # Instant from cache -- no second browse request.
    assert calls == []
    assert tree._current_source_rows[0].label == "Cached"


def test_activation_hands_row_to_callback(tree):
    activated = []
    tree.on_source_node_activated = activated.append
    rows = [_node("Playable")]
    tree.set_source_rows("somafm", rows)
    tree.station_list.Select(0)
    event = mock.Mock()
    event.GetIndex.return_value = 0
    tree._on_station_activated_event(event)
    assert activated and activated[0].label == "Playable"