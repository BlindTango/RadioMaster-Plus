"""Shortcut catalogue, validation, and compatibility tests."""

from radiomaster.ui.help_dialog import render_help_topics
from radiomaster.ui.shortcut_editor import (
    DEFAULT_SHORTCUTS,
    find_conflict,
    load_shortcuts,
    shortcut_signature,
    shortcut_to_accel,
    shortcut_to_global_spec,
)


class FakeConfig:
    def __init__(self, shortcuts=None):
        self.shortcuts = shortcuts or {}

    def get(self, key, default=None):
        return self.shortcuts if key == "shortcuts" else default


def test_default_shortcuts_are_unique() -> None:
    signatures = [
        shortcut_signature(shortcut)
        for shortcut in DEFAULT_SHORTCUTS.values()
        if shortcut["key"]
    ]
    assert len(signatures) == len(set(signatures))


def test_catalogue_includes_menus_panels_and_player_controls() -> None:
    required = {
        "open_file", "import_opml", "toggle_lyrics", "effect_equalizer",
        "keyboard_shortcuts", "check_updates", "about", "panel_youtube",
        "play_pause", "stop", "volume_up", "volume_down", "rate_up", "rate_down",
        "speed_up", "speed_down",
    }
    assert required <= DEFAULT_SHORTCUTS.keys()


def test_left_and_right_modifiers_conflict_at_runtime() -> None:
    shortcuts = {
        "first": {"key": "A", "modifiers": ["Left Ctrl"]},
    }
    candidate = {"key": "A", "modifiers": ["Right Ctrl"]}
    assert find_conflict(shortcuts, candidate) == "first"


def test_windows_modifier_is_not_silently_converted_to_ctrl() -> None:
    assert shortcut_to_accel({"key": "A", "modifiers": ["Left Windows"]}) is None
    assert shortcut_to_global_spec({"key": "A", "modifiers": ["Left Windows"]}) == "Windows+A"


def test_global_scope_is_loaded_with_assignment() -> None:
    loaded = load_shortcuts(FakeConfig({
        "play_pause": {"key": "F8", "modifiers": [], "global": True},
    }))
    assert loaded["play_pause"]["global"] is True


def test_help_topics_use_current_shortcut_and_scope() -> None:
    config = FakeConfig({
        "play_pause": {"key": "F8", "modifiers": [], "global": True},
        "stop": {"key": "F9", "modifiers": [], "global": False},
    })
    rendered = render_help_topics([
        ("Playback", "Play: {shortcut:play_pause}. Stop: {shortcut:stop}."),
    ], config)
    assert rendered == [("Playback", "Play: F8 (Global). Stop: F9 (In app).")]


def test_help_topics_show_unassigned_shortcuts() -> None:
    config = FakeConfig({
        "play_pause": {"key": "", "modifiers": [], "global": False},
    })
    rendered = render_help_topics([
        ("Playback", "Play: {shortcut:play_pause}."),
    ], config)
    assert rendered[0][1] == "Play: Unassigned."


def test_legacy_saved_action_names_are_migrated() -> None:
    loaded = load_shortcuts(FakeConfig({
        "preferences": {"key": "F2", "modifiers": []},
        "show_shortcuts": {"key": "F3", "modifiers": []},
    }))
    assert loaded["settings"]["key"] == "F2"
    assert loaded["keyboard_shortcuts"]["key"] == "F3"
