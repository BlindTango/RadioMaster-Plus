"""Application class for RadioMaster+."""

import wx
import logging

from radiomaster.utils.logging_setup import setup_logging
from radiomaster.utils.paths import get_paths
from radiomaster.utils.config import ConfigManager
from radiomaster.database.connection import DatabaseManager
from radiomaster.ui.main_window import MainWindow
from radiomaster.ui.theme_manager import ThemeManager
from radiomaster.services.download_manager import DownloadManager
from radiomaster.services.scheduler_service import SchedulerService
from radiomaster.services.lyrics_service import set_lyrics_repository
from radiomaster.database.repository import LyricsRepository
from radiomaster import __app_name__, __version__


class RadioMasterApp(wx.App):
    """Main application class for RadioMaster+."""

    # Must match packaging/radiomaster.iss's AppMutex exactly -- that's
    # what lets the installer reliably detect "is RadioMaster+ currently
    # running" *before* it starts overwriting files, instead of only
    # reacting after hitting a locked file mid-copy. Without this, the
    # in-app updater's launch-installer-then-close-self sequence raced
    # against the installer overwriting _internal/*.dll while the old
    # process was still shutting down, occasionally leaving a corrupted
    # DLL behind ("Failed to load Python DLL... LoadLibrary: the
    # specified module could not be found" on the very next launch).
    INSTANCE_MUTEX_NAME = "RadioMasterPlusSingleInstance"

    def __init__(self) -> None:
        self._config: ConfigManager | None = None
        self._paths: dict[str, str] = {}
        self._db: DatabaseManager | None = None
        self._theme_manager: ThemeManager | None = None
        self._main_window: MainWindow | None = None
        self._download_manager: DownloadManager | None = None
        self._scheduler_service: SchedulerService | None = None
        self._instance_mutex = None
        super().__init__()

    def OnInit(self) -> bool:
        """Initialize the application."""
        self.SetAppName(__app_name__)
        self.SetVendorName(__app_name__)

        # Held for the process's entire lifetime (released/closed in
        # OnExit) -- its mere existence is the signal AppMutex checks for,
        # not anything the value is used for.
        try:
            import ctypes
            self._instance_mutex = ctypes.windll.kernel32.CreateMutexW(
                None, False, self.INSTANCE_MUTEX_NAME
            )
        except Exception:
            self.logger = logging.getLogger(__app_name__)
            self.logger.warning("Could not create single-instance mutex", exc_info=True)

        # OnInit() runs before MainLoop() starts, so nothing is pumping
        # events yet -- wx.Yield() forces the splash to actually paint
        # once before the (potentially slow: SQLite station catalog,
        # service startup) synchronous init below blocks the thread.
        from radiomaster.ui.splash import show_splash
        splash = show_splash()
        wx.Yield()

        # Initialize paths
        self._paths = get_paths()

        # Load configuration
        self._config = ConfigManager(self._paths["config"])
        # Every ConfigManager.get_instance() call anywhere in the app (a
        # dozen-plus services/panels that read settings without being
        # handed a reference directly) must see this exact object -- see
        # ConfigManager.set_instance()'s docstring for why this matters.
        ConfigManager.set_instance(self._config)

        # Setup logging
        setup_logging(
            level=self._config.get("logging.level", default="info"),
            log_dir=self._paths["logs"],
        )
        self.logger = logging.getLogger(__app_name__)
        self.logger.info(f"Starting {__app_name__} v{__version__}")

        # Initialize database
        self._db = DatabaseManager(self._paths["data"])
        self._db.initialize()

        # Initialize theme manager
        self._theme_manager = ThemeManager(self._config)

        # Apply the saved UI language before any menu/label is built (they
        # all go through _() at construction time) -- previously only the
        # View > Language menu ever touched I18nManager, so General >
        # Language in Settings saved a value nothing read, even on restart.
        from radiomaster.i18n import I18nManager
        I18nManager().set_language(self._config.get("general", "language", default="en"))

        # Initialize services
        max_concurrent = self._config.get("downloads", "max_concurrent", default=3)
        self._download_manager = DownloadManager(max_concurrent)
        # Without this wiring, DownloadManager ran real yt-dlp/podcast
        # downloads to completion but never told the "downloads" table --
        # every row it created stayed at its insert-time status forever
        # (queued/downloading), so the Downloads tab's Active list showed
        # a download that had actually already finished (or failed) with
        # no way to tell, and it never moved to History.
        from radiomaster.database.repository import DownloadRepository
        download_repo = DownloadRepository(self._db)
        self._download_manager.on_progress(
            lambda did, pct: download_repo.update_progress(did, pct, status="downloading")
        )
        self._download_manager.on_complete(
            lambda did, path: download_repo.mark_completed(did, path)
        )
        self._download_manager.on_error(
            lambda did, msg: download_repo.update_progress(did, 0.0, status="failed")
        )
        self._download_manager.start()

        from radiomaster.utils.paths import get_recordings_dir
        rec_dir = get_recordings_dir()
        self._scheduler_service = SchedulerService(rec_dir)
        from radiomaster.database.repository import ScheduleRepository
        self._scheduler_service.load_schedules(ScheduleRepository(self._db).get_all())
        self._scheduler_service.start()

        # ------------------------------------------------------------------
        # Initialise lyrics cache repository and inject it into the static
        # ``LyricsService``.  This allows the service to use the SQLite cache
        # without needing to be instantiated.
        # ------------------------------------------------------------------
        lyrics_repo = LyricsRepository(self._db)
        set_lyrics_repository(lyrics_repo)

        # Create and show main window
        self._main_window = MainWindow(
            self._config,
            self._db,
            self._theme_manager,
            self._paths,
            self._scheduler_service,
        )
        self._main_window.Show()
        self.SetTopWindow(self._main_window)
        splash.Close()

        return True

    def OnExit(self) -> int:
        """Clean up on exit."""
        self.logger.info(f"Shutting down {__app_name__}")
        if self._main_window:
            # Backstop for MainWindow._on_close (EVT_CLOSE), which is what
            # normally stops playback before the frame is destroyed. Cheap
            # to call again here in case exit happened some other way.
            # wait=False for the same reason _on_close uses it -- OnExit()
            # blocking here delays process exit exactly when an installer
            # (see AppMutex) may be waiting on it to actually be gone.
            self._main_window.engine.stop(wait=False)
            # Same backstop reasoning for the tray icon: a leftover icon
            # only disappears once the user mouses over it if this doesn't
            # run (e.g. exit via OS session end while hidden to the tray).
            if self._main_window._tray_icon:
                self._main_window._tray_icon.RemoveIcon()
                self._main_window._tray_icon.Destroy()
                self._main_window._tray_icon = None
        if self._config:
            # Same backstop reasoning as engine.stop() above: MainWindow's
            # _on_close (EVT_CLOSE) is what normally persists
            # volume/rate/pan and any other in-memory config changes to
            # disk; this covers exit paths that bypass it.
            self._config.save()
        if self._download_manager:
            self._download_manager.stop()
        if self._scheduler_service:
            self._scheduler_service.stop()
        if self._db:
            self._db.close()
        if self._instance_mutex:
            # Releases the AppMutex signal an installer update checks for
            # -- without this the OS wouldn't reclaim it until process
            # exit anyway, but that's exactly the ambiguous window (frame
            # closed, cleanup still running) an installer launched by the
            # in-app updater could race against.
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(self._instance_mutex)
            except Exception:
                pass
        return 0

    @property
    def config(self) -> ConfigManager:
        assert self._config is not None
        return self._config

    @property
    def db(self) -> DatabaseManager:
        assert self._db is not None
        return self._db

    @property
    def theme_manager(self) -> ThemeManager:
        assert self._theme_manager is not None
        return self._theme_manager

    @property
    def paths(self) -> dict[str, str]:
        return self._paths

    @property
    def download_manager(self) -> DownloadManager:
        assert self._download_manager is not None
        return self._download_manager

    @property
    def scheduler_service(self) -> SchedulerService:
        assert self._scheduler_service is not None
        return self._scheduler_service
