"""Entry point for RadioMaster+."""

import sys


def main() -> None:
    """Launch the RadioMaster+ application."""
    if "--bass-host" in sys.argv:
        # The windowed PyInstaller bootloader normally replaces standard
        # streams with None. A child launched with redirected pipe handles
        # still has usable CRT descriptors, so restore them for the JSON IPC.
        if sys.stdin is None:
            sys.stdin = open(0, "r", encoding="utf-8", errors="replace")
        if sys.stdout is None:
            sys.stdout = open(1, "w", encoding="utf-8", errors="replace",
                              buffering=1)
        from radiomaster.engine.bass_host import main as bass_host_main
        bass_host_main()
        return

    # Must run before anything else can fail -- see launch_log's docstring.
    # The worst thing an app can do when it cannot start is nothing at all
    # (borrowed from Quill Radio 3.0.4's launcher): this keeps a record of
    # everything that goes wrong from the very first import on.
    from radiomaster.utils.launch_log import start as launch_log_start
    launch_log_start()

    from radiomaster.app import RadioMasterApp
    app = RadioMasterApp()
    app.MainLoop()


if __name__ == "__main__":
    main()
