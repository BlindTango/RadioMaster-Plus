"""Entry point for RadioMaster+."""

import sys
import wx

from radiomaster.app import RadioMasterApp


def main() -> None:
    """Launch the RadioMaster+ application."""
    app = RadioMasterApp()
    app.MainLoop()


if __name__ == "__main__":
    main()
