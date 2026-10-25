"""Translate wx widget and menu labels as they are created.

The UI is written with plain English labels. Rather than wrapping every one in
a gettext call, this installs thin wrappers around the wx constructors and
menu methods that take visible text, and passes that text through
``I18nManager.translate_label``. Nothing is installed for English, so English
behaviour is untouched. Text built at run time (f-strings, status messages)
is not covered; it stays English.
"""

from __future__ import annotations

import functools
import logging

import wx

log = logging.getLogger("radiomaster")

_installed = False


def _translate(text):
    from radiomaster.i18n import I18nManager
    return I18nManager().translate_label(text) if isinstance(text, str) else text


def _wrap_init(cls, label_index: int | None, kwargs=("label",)) -> None:
    """Wrap cls.__init__: translate the named keyword(s) and, when given, the
    positional argument at ``label_index`` (counting after self)."""
    original = cls.__init__

    @functools.wraps(original)
    def wrapper(self, *args, **kw):
        if label_index is not None and len(args) > label_index:
            args = list(args)
            args[label_index] = _translate(args[label_index])
        for name in kwargs:
            if name in kw:
                kw[name] = _translate(kw[name])
        return original(self, *args, **kw)

    cls.__init__ = wrapper


def _wrap_method(cls, name: str, positions: tuple[int, ...], kwargs: tuple[str, ...] = ()) -> None:
    original = getattr(cls, name)

    @functools.wraps(original)
    def wrapper(self, *args, **kw):
        args = list(args)
        for i in positions:
            if len(args) > i:
                args[i] = _translate(args[i])
        for k in kwargs:
            if k in kw:
                kw[k] = _translate(kw[k])
        return original(self, *args, **kw)

    setattr(cls, name, wrapper)


def install() -> None:
    """Wrap the wx classes once; safe to call again."""
    global _installed
    if _installed:
        return
    _installed = True
    try:
        # (parent, id, label, ...)
        for cls in (wx.StaticText, wx.Button, wx.CheckBox, wx.RadioButton,
                    wx.StaticBox, wx.ToggleButton):
            _wrap_init(cls, 2)
        # (parent, id, title, ...)
        for cls in (wx.Dialog, wx.Frame):
            _wrap_init(cls, 2, kwargs=("title",))
        # (parent, message, caption)
        for cls in (wx.TextEntryDialog, wx.PasswordEntryDialog, wx.MessageDialog):
            _wrap_init(cls, None, kwargs=("message", "caption"))
            original = cls.__init__

            @functools.wraps(original)
            def dialog_init(self, *args, _orig=original, **kw):
                args = list(args)
                for i in (1, 2):
                    if len(args) > i:
                        args[i] = _translate(args[i])
                return _orig(self, *args, **kw)
            cls.__init__ = dialog_init

        # wx.MessageBox(message, caption, ...)
        original_box = wx.MessageBox

        @functools.wraps(original_box)
        def message_box(message, caption="Message", *args, **kw):
            return original_box(_translate(message), _translate(caption), *args, **kw)
        wx.MessageBox = message_box

        # Menus: Append(id, item, help), AppendCheckItem(...), AppendSubMenu(menu, text, help)
        for name in ("Append", "AppendCheckItem", "AppendRadioItem"):
            _wrap_method(wx.Menu, name, (1, 2), ("item", "helpString"))
        _wrap_method(wx.Menu, "AppendSubMenu", (1, 2), ("text", "help"))
        _wrap_method(wx.MenuBar, "Append", (1,), ("title",))
        # Tabs: AddPage(page, text, ...)
        for cls in (wx.Listbook, wx.Notebook):
            _wrap_method(cls, "AddPage", (1,), ("text",))
        # Window title / label changes made after construction.
        _wrap_method(wx.Frame, "SetTitle", (0,))
        _wrap_method(wx.Dialog, "SetTitle", (0,))
        _wrap_method(wx.StaticText, "SetLabel", (0,))
        _wrap_method(wx.Button, "SetLabel", (0,))
    except Exception as exc:  # a wx build without one of these: stay English
        log.warning("UI translation hooks only partly installed: %s", exc)
