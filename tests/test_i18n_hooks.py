"""UI translation: .po parsing and the wx label hooks, on real widgets."""

import wx

from radiomaster.i18n import I18nManager
from radiomaster.i18n.po import parse_po


def test_po_parser_handles_continuations_escapes_and_untranslated(tmp_path):
    po = tmp_path / "x.po"
    po.write_text(
        '# comment\nmsgid ""\nmsgstr "Header: x\n"\n\n'
        'msgid "Hello"\nmsgstr "Hola"\n\n'
        'msgid "Long one"\nmsgstr ""\n"Parte uno "\n"parte dos"\n\n'
        'msgid "Line\\nbreak"\nmsgstr "Salto\\nlinea"\n\n'
        'msgid "Pending"\nmsgstr ""\n', encoding="utf-8")
    entries = parse_po(str(po))
    assert entries["Hello"] == "Hola"
    assert entries["Long one"] == "Parte uno parte dos"
    assert entries["Line\nbreak"] == "Salto\nlinea"
    assert "Pending" not in entries and "" not in entries


def test_translate_label_keeps_shortcuts_and_falls_back_without_ampersand():
    m = I18nManager()
    saved = (m._current_language, dict(m._catalogues))
    try:
        m._current_language = "xx"
        m._catalogues["xx"] = {"&File": "&Archivo", "Open": "Abrir", "Hi": "Hola"}
        assert m.translate_label("&File") == "&Archivo"
        assert m.translate_label("&Open\tCtrl+O") == "Abrir\tCtrl+O"   # no '&' form -> plain
        assert m.translate_label("Unknown") == "Unknown"
        m._current_language = "en"
        assert m.translate_label("&File") == "&File"
    finally:
        m._current_language, m._catalogues = saved[0], saved[1]


def test_wx_hooks_translate_real_widgets_and_menus():
    from radiomaster.i18n import wx_hooks
    app = wx.App.Get() or wx.App(False)
    m = I18nManager()
    saved = (m._current_language, dict(m._catalogues))
    wx_hooks._installed = False
    try:
        m._current_language = "xx"
        m._catalogues["xx"] = {"Play": "Reproducir", "&File": "&Archivo", "Open": "Abrir",
                               "Settings": "Ajustes", "Radio": "Radio FM"}
        wx_hooks.install()
        frame = wx.Frame(None, title="Settings")
        assert frame.GetTitle() == "Ajustes"
        button = wx.Button(frame, label="Play")
        assert button.GetLabel() == "Reproducir"
        text = wx.StaticText(frame, label="Play")
        assert text.GetLabel() == "Reproducir"
        check = wx.CheckBox(frame, label="Unmapped label")
        assert check.GetLabel() == "Unmapped label"
        bar, menu = wx.MenuBar(), wx.Menu()
        item = menu.Append(wx.ID_ANY, "Open\tCtrl+O")
        assert item.GetItemLabel().startswith("Abrir")
        bar.Append(menu, "&File")
        assert bar.GetMenuLabel(0) == "&Archivo"
        book = wx.Listbook(frame)
        book.AddPage(wx.Panel(book), "Radio")
        assert book.GetPageText(0) == "Radio FM"
        frame.Destroy()
    finally:
        wx_hooks.uninstall()
        m._current_language, m._catalogues = saved
        app.ProcessPendingEvents()


import pytest

LANGS = ["es", "fr", "de", "it", "pt", "ru", "ja", "zh"]


@pytest.mark.parametrize("lang", LANGS)
def test_catalogue_is_complete_and_consistent(lang):
    import os
    import re
    from radiomaster import i18n
    base = os.path.join(os.path.dirname(i18n.__file__))
    reference = parse_po(os.path.join(base, "es", "LC_MESSAGES", "radiomaster.po"))
    entries = parse_po(os.path.join(base, lang, "LC_MESSAGES", "radiomaster.po"))
    assert set(entries) == set(reference), f"{lang} does not cover the same strings"
    token = re.compile(r"\{[a-z_]+\}")
    for english, translated in entries.items():
        # placeholders must survive translation
        assert sorted(token.findall(english)) == sorted(token.findall(translated)), (lang, english)
        # a label with an & accelerator keeps one
        if re.search(r"(?<!&)&(?!&)", english):
            assert "&" in translated, (lang, f"accelerator lost: {english!r}")
        # an explicit newline in the English stays a newline
        assert english.count("\n") == translated.count("\n"), (lang, english)
        assert translated.strip() == translated, (lang, english)


@pytest.mark.parametrize("lang", LANGS)
def test_language_is_offered_in_settings(lang):
    from radiomaster.i18n import LANGUAGES
    assert lang in LANGUAGES


def test_spanish_translates_menu_and_dialog_text():
    m = I18nManager()
    saved = (m._current_language, dict(m._catalogues))
    try:
        m._current_language = "es"
        assert m.translate_label("&File") == "&Archivo"
        assert m.translate_label("&Open File...\tCtrl+O") == "&Abrir archivo...\tCtrl+O"
        assert m.translate_label("Settings") == "Configuración"
        assert m.translate_label("A string nobody translated") == "A string nobody translated"
    finally:
        m._current_language, m._catalogues = saved
