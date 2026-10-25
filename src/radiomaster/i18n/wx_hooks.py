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
_originals: list[tuple[object, str, object, bool]] = []


def _translate(text):
    from radiomaster.i18n import I18nManager
    return I18nManager().translate_label(text) if isinstance(text, str) else text


def _wrap_init(cls, label_index: int | None, kwargs=("label",)) -> None:
    """Wrap cls.__init__: translate the named keyword(s) and, when given, the
    positional argument at ``label_index`` (counting after self)."""
    original = cls.__init__
    _originals.append((cls, "__init__", vars(cls).get("__init__", original), "__init__" in vars(cls)))

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
    _originals.append((cls, name, vars(cls).get(name, original), name in vars(cls)))

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
        _originals.append((wx, "MessageBox", original_box, True))

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
    except Exception as exc:  # a wx build without one of these: stay English
        log.warning("UI translation hooks only partly installed: %s", exc)


def uninstall() -> None:
    """Put the original wx constructors and methods back (used by tests)."""
    global _installed
    for owner, name, original, had_own in reversed(_originals):
        if had_own:
            setattr(owner, name, original)
        else:
            try:
                delattr(owner, name)    # fall back to the inherited one again
            except AttributeError:
                pass
    _originals.clear()
    _installed = False
