"""Tests for the multi-source station catalog framework."""

import json
from unittest import mock

import pytest

from radiomaster.services.sources import (
    CONFIG_KEY,
    DEFAULT_ENABLED,
    SourceNode,
    SourceRegistry,
    SourceUnavailable,
    StationRef,
    StationSource,
)
from radiomaster.services.sources.acb_media import ACBMediaSource
from radiomaster.services.sources.base import describe_source
from radiomaster.services.sources.internet_archive import InternetArchiveSource
from radiomaster.services.sources.somafm import SomaFMSource


class _FakeConfig:
    """Mimics ConfigManager's dotted-key get/set for registry tests."""

    def __init__(self):
        self.data = {}

    def get(self, *keys, default=None):
        value = self.data
        flat = []
        for k in keys:
            flat.extend(k.split("."))
        for k in flat:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value

    def set(self, *keys, value=None):
        flat = []
        for k in keys:
            flat.extend(k.split("."))
        target = self.data
        for k in flat[:-1]:
            target = target.setdefault(k, {})
        target[flat[-1]] = value


# ---------------------------------------------------------------- base


def test_base_source_raises_specific_unavailable():
    source = StationSource()
    source.label = "Test Source"
    with pytest.raises(SourceUnavailable) as excinfo:
        source.browse("")
    assert "Test Source" in str(excinfo.value)


def test_describe_source_offline():
    source = ACBMediaSource()
    sentence = describe_source(source)
    assert "ACB Media" in sentence
    assert "works offline" in sentence


def test_describe_source_online():
    source = InternetArchiveSource()
    sentence = describe_source(source)
    assert "needs the internet" in sentence


# ---------------------------------------------------------------- ACB Media


def test_acb_media_browse_returns_ten_streams():
    nodes = ACBMediaSource().browse("")
    assert len(nodes) == 10
    assert all(n.station is not None for n in nodes)
    assert all(n.station.url.startswith("https://streaming.live365.com/") for n in nodes)


def test_acb_media_browse_children_empty():
    assert ACBMediaSource().browse("stream:1") == []


def test_acb_media_search_refuses():
    with pytest.raises(SourceUnavailable):
        ACBMediaSource().search("anything")


def test_acb_media_rows_carry_their_truth():
    node = ACBMediaSource().browse("")[0]
    assert "Blind-community radio" in node.note
    assert node.station.source_id == "acb_media"


# ---------------------------------------------------------------- SomaFM


_SOMAFM_PAYLOAD = {
    "channels": [
        {
            "id": "groovesalad",
            "title": "Groove Salad",
            "description": "A nicely chilled plate of ambient beats.",
            "genre": "ambient",
            "dj": "Rusty Hodge",
            "playlists": [
                {"url": "https://api.somafm.com/groovesalad130.pls", "format": "aac"},
                {"url": "https://api.somafm.com/groovesalad.pls", "format": "mp3"},
            ],
        },
        {
            "id": "bootliquor",
            "title": "Boot Liquor",
            "description": "Americana roots music.",
            "genre": "americana",
            "dj": "Roy",
            "playlists": [
                {"url": "https://api.somafm.com/bootliquor320.pls", "format": "mp3"},
            ],
        },
    ]
}


def test_somafm_browse_groups_by_genre(tmp_path):
    source = SomaFMSource(str(tmp_path))
    with mock.patch.object(source, "_fetch_channels", return_value=_SOMAFM_PAYLOAD["channels"]):
        root = source.browse("")
    labels = [n.label for n in root]
    assert "Ambient" in labels and "Americana" in labels
    assert all(n.has_children for n in root)


def test_somafm_prefers_mp3_playlist(tmp_path):
    source = SomaFMSource(str(tmp_path))
    with mock.patch.object(source, "_fetch_channels", return_value=_SOMAFM_PAYLOAD["channels"]):
        root = source.browse("")
        ambient = next(n for n in root if n.label == "Ambient")
        channels = source.browse(ambient.path)
    assert channels[0].station.url.endswith("groovesalad.pls")


def test_somafm_search_matches_title_and_genre(tmp_path):
    source = SomaFMSource(str(tmp_path))
    with mock.patch.object(source, "_fetch_channels", return_value=_SOMAFM_PAYLOAD["channels"]):
        assert len(source.search("groove")) == 1
        assert len(source.search("americana")) == 1
        assert source.search("nonexistent") == []


def test_somafm_cache_answers_offline(tmp_path):
    """A cached channel list keeps answering with no network at all."""
    cache_path = tmp_path / "somafm_channels.json"
    cache_path.write_text(json.dumps(_SOMAFM_PAYLOAD), encoding="utf-8")
    source = SomaFMSource(str(tmp_path))
    # _fetch_channels would raise if called; the cache must satisfy first.
    with mock.patch.object(source, "_fetch_channels",
                           side_effect=SourceUnavailable("SomaFM", "offline test")):
        root = source.browse("")
    assert len(root) == 2


def test_somafm_no_cache_no_network_raises(tmp_path):
    source = SomaFMSource(str(tmp_path))
    with mock.patch.object(source, "_fetch_channels",
                           side_effect=SourceUnavailable("SomaFM", "down")):
        with pytest.raises(SourceUnavailable):
            source.browse("")


# ---------------------------------------------------------------- Internet Archive


_IA_PAYLOAD = {
    "response": {
        "docs": [
            {"identifier": "gd1977-05-08", "title": "Grateful Dead Live at Barton Hall",
             "creator": "Grateful Dead"},
            {"identifier": "no-creator", "title": "Untitled", "creator": ""},
        ]
    }
}


def test_internet_archive_search_builds_nodes():
    source = InternetArchiveSource()
    with mock.patch("radiomaster.services.sources.internet_archive.requests.get") as get:
        get.return_value.json.return_value = _IA_PAYLOAD
        get.return_value.raise_for_status.return_value = None
        nodes = source.search("grateful dead")
    assert len(nodes) == 2
    first = nodes[0]
    assert first.station.url == "https://archive.org/download/gd1977-05-08/gd1977-05-08_vbr.mp3"
    assert "Public domain or Creative Commons" in first.note
    # A doc with no creator must not show a dangling dash.
    assert "—" not in nodes[1].label


def test_internet_archive_empty_query_returns_empty():
    assert InternetArchiveSource().search("  ") == []


def test_internet_archive_browse_refuses():
    with pytest.raises(SourceUnavailable):
        InternetArchiveSource().browse("")


# ---------------------------------------------------------------- registry


def test_registry_lists_all_sources(tmp_path):
    registry = SourceRegistry(_FakeConfig(), str(tmp_path))
    ids = {s.id for s in registry.all_sources()}
    assert {"somafm", "acb_media", "internet_archive"} <= ids


def test_registry_defaults_when_config_empty(tmp_path):
    registry = SourceRegistry(_FakeConfig(), str(tmp_path))
    enabled = {s.id for s in registry.enabled_sources()}
    assert enabled == set(DEFAULT_ENABLED) & {s.id for s in registry.all_sources()}


def test_registry_respects_config_selection(tmp_path):
    config = _FakeConfig()
    config.set("radio.enabled_sources", value=["acb_media"])
    registry = SourceRegistry(config, str(tmp_path))
    assert [s.id for s in registry.enabled_sources()] == ["acb_media"]


def test_registry_ignores_unknown_ids(tmp_path):
    config = _FakeConfig()
    config.set("radio.enabled_sources", value=["acb_media", "ghost_source"])
    registry = SourceRegistry(config, str(tmp_path))
    assert [s.id for s in registry.enabled_sources()] == ["acb_media"]


def test_registry_set_enabled_round_trips(tmp_path):
    config = _FakeConfig()
    registry = SourceRegistry(config, str(tmp_path))
    registry.set_enabled_ids(["somafm", "acb_media"])
    assert set(registry.enabled_ids()) == {"somafm", "acb_media"}


def test_registry_config_key():
    assert CONFIG_KEY == "radio.enabled_sources"