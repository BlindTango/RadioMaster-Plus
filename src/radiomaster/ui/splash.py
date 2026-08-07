"""Startup splash screen -- drawn at runtime from the app icon plus text,
no separate splash image asset needed.
"""

from __future__ import annotations

import os

import wx
import wx.adv

from radiomaster import __app_name__, __copyright__, __version__
from radiomaster.utils.paths import get_resource_path

SPLASH_SIZE = (420, 300)
SPLASH_MS = 1800


def _build_bitmap() -> wx.Bitmap:
    bitmap = wx.Bitmap(*SPLASH_SIZE)
    dc = wx.MemoryDC(bitmap)
    dc.SetBackground(wx.Brush(wx.Colour(12, 28, 56)))
    dc.Clear()

    icon_path = get_resource_path("icon.png")
    if os.path.exists(icon_path):
        icon_img = wx.Image(icon_path)
        icon_size = 120
        icon_img = icon_img.Scale(icon_size, icon_size, wx.IMAGE_QUALITY_HIGH)
        dc.DrawBitmap(wx.Bitmap(icon_img), (SPLASH_SIZE[0] - icon_size) // 2, 24)

    dc.SetTextForeground(wx.Colour(255, 255, 255))
    title_font = wx.Font(24, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_BOLD)
    dc.SetFont(title_font)
    title = __app_name__
    tw, th = dc.GetTextExtent(title)
    dc.DrawText(title, (SPLASH_SIZE[0] - tw) // 2, 155)

    dc.SetTextForeground(wx.Colour(140, 190, 255))
    sub_font = wx.Font(11, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
    dc.SetFont(sub_font)
    subtitle = "Accessible Radio, Podcast & Media Player"
    sw, sh = dc.GetTextExtent(subtitle)
    dc.DrawText(subtitle, (SPLASH_SIZE[0] - sw) // 2, 155 + th + 6)

    version_text = f"v{__version__}"
    vw, vh = dc.GetTextExtent(version_text)
    dc.DrawText(version_text, (SPLASH_SIZE[0] - vw) // 2, SPLASH_SIZE[1] - vh - 36)

    copy_font = wx.Font(8, wx.FONTFAMILY_SWISS, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL)
    dc.SetFont(copy_font)
    dc.SetTextForeground(wx.Colour(130, 150, 180))
    cw, ch = dc.GetTextExtent(__copyright__)
    dc.DrawText(__copyright__, (SPLASH_SIZE[0] - cw) // 2, SPLASH_SIZE[1] - ch - 12)

    dc.SelectObject(wx.NullBitmap)
    return bitmap


def show_splash() -> wx.adv.SplashScreen:
    """Show the startup splash for SPLASH_MS, then auto-close.

    Must be called after a wx.App exists (needs a DC) but the splash
    itself does not block __init__ from continuing to build the main
    window underneath it -- SPLASH_TIMEOUT + SPLASH_NO_CENTER_ON_PARENT
    variants would; plain SPLASH_TIMEOUT closes itself asynchronously.
    """
    bitmap = _build_bitmap()
    return wx.adv.SplashScreen(
        bitmap,
        wx.adv.SPLASH_CENTRE_ON_SCREEN | wx.adv.SPLASH_TIMEOUT,
        SPLASH_MS, None,
        style=wx.BORDER_SIMPLE | wx.FRAME_NO_TASKBAR,
    )
