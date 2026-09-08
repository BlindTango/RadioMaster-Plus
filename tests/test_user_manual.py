"""Coverage and navigation checks for the complete offline manual."""

import re

import pytest
import wx

from radiomaster.ui.effects_data import BUILTIN_PRESETS, EFFECT_IDS, EFFECT_LABELS, PARAM_DEFS
from radiomaster.ui.help_dialog import HelpDialog, render_help_topics
from radiomaster.ui.shortcut_editor import DEFAULT_SHORTCUTS
from radiomaster.ui.user_manual import CATEGORY_ORDER, MANUAL_SECTIONS, TOPIC_CATEGORIES, USER_MANUAL_TOPICS


def test_topics_have_unique_titles_and_explicit_categories():
    titles = [title for title, _body in USER_MANUAL_TOPICS]
    assert len(titles) == len(set(titles))
    assert set(TOPIC_CATEGORIES) == set(titles)
    assert set(TOPIC_CATEGORIES.values()) == set(CATEGORY_ORDER)
    assert all(topics for _category, topics in MANUAL_SECTIONS)


def test_every_settings_category_has_a_topic():
    from radiomaster.ui import settings_dialog

    for name in ("General", "Playback", "Radio", "Podcasts", "Audiobooks", "Downloads", "Recordings",
                 "Network", "Accessibility", "Advanced"):
        panel = getattr(settings_dialog, f"{name}Panel")
        title = {"Podcasts": "Podcast", "Audiobooks": "Audiobook", "Downloads": "Download", "Recordings": "Recording"}.get(name, name)
        assert panel.title
        assert TOPIC_CATEGORIES[f"{title} Settings"] == "Settings"


@pytest.mark.parametrize("effect_id", EFFECT_IDS)
def test_every_effect_has_its_presets_and_parameters(effect_id):
    body = dict(USER_MANUAL_TOPICS)[f"{EFFECT_LABELS[effect_id]} Reference"]
    assert all(name in body for name in BUILTIN_PRESETS[effect_id])
    assert all(label in body for label, *_rest in PARAM_DEFS[effect_id])


def test_shortcut_reference_covers_catalogue_and_resolves_custom_assignments():
    class Config:
        def get(self, key, default=None):
            return {"user_manual": {"key": "F12", "modifiers": [], "global": True}} if key == "shortcuts" else default

    rendered = dict(render_help_topics(USER_MANUAL_TOPICS, Config()))
    reference = rendered["Keyboard Shortcut Reference"]
    assert all(item["description"] in reference for item in DEFAULT_SHORTCUTS.values())
    assert "F12 (Global)" in rendered["Using This Manual"]
    for body in rendered.values():
        assert not re.search(r"\{(?:shortcut:|shortcut_reference|panel_shortcuts)", body)


def test_manual_dialog_category_overview_and_topic_selection():
    app = wx.App.Get() or wx.App(False)
    frame = wx.Frame(None)
    dialog = HelpDialog(frame)
    try:
        tree = dialog.topic_tree
        category, cookie = tree.GetFirstChild(dialog._root)
        seen = []
        for expected_category, topics in MANUAL_SECTIONS:
            assert tree.GetItemText(category) == expected_category
            tree.SelectItem(category)
            assert dialog.content.GetValue().startswith(expected_category)
            assert all(title in dialog.content.GetValue() for title, _body in topics)
            topic, child_cookie = tree.GetFirstChild(category)
            for title, _body in topics:
                tree.SelectItem(topic)
                assert dialog.content.GetValue().startswith(title + "\n\n")
                assert "{shortcut:" not in dialog.content.GetValue()
                seen.append(tree.GetItemText(topic))
                topic, child_cookie = tree.GetNextChild(category, child_cookie)
            category, cookie = tree.GetNextChild(dialog._root, cookie)
        assert seen == [title for title, _body in USER_MANUAL_TOPICS]
    finally:
        dialog.Destroy()
        frame.Destroy()
        app.ProcessPendingEvents()
