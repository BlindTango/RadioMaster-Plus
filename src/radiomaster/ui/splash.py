"""Native, non-animated startup feedback retained until initialization finishes."""

import wx

from radiomaster import __app_name__, __version__


def show_splash() -> wx.Dialog:
    """Show native text in system colours; the caller owns the window lifetime.

    No animation or timeout is used, including when Reduce motion is enabled.
    """
    window = wx.Dialog(None, title=f"{__app_name__} is starting",
                       style=wx.CAPTION | wx.BORDER_SIMPLE)
    layout = wx.BoxSizer(wx.VERTICAL)
    title = wx.StaticText(window, label=f"{__app_name__} v{__version__}")
    layout.Add(title, 0, wx.ALL, 16)
    # Focused native text exposes the message to screen readers instead of
    # drawing it into a bitmap. System colours respect high contrast settings.
    message = wx.TextCtrl(
        window, value=f"{__app_name__} is starting. Please wait.",
        style=wx.TE_READONLY | wx.BORDER_NONE, size=(380, -1),
    )
    layout.Add(message, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM | wx.EXPAND, 16)
    window.SetSizerAndFit(layout)
    window.CentreOnScreen()
    # Dismissing the indicator must not destroy an object still owned by
    # startup or interrupt application initialization.
    window.Bind(wx.EVT_CLOSE, lambda event: window.Hide())
    window.Bind(wx.EVT_BUTTON, lambda event: window.Hide(), id=wx.ID_CANCEL)
    window.Show()
    message.SetFocus()
    window.Update()
    return window
