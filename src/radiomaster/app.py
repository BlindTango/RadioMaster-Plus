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

    def __init__(self) -> None:
        self._config: ConfigManager | None = None
        self._paths: dict[str, str] = {}
        self._db: DatabaseManager | None = None
        self._theme_manager: ThemeManager | None = None
        self._main_window: MainWindow | None = None
        self._download_manager: DownloadManager | None = None
        self._scheduler_service: SchedulerService | None = None
        super().__init__()

    def OnInit(self) -> bool:
        """Initialize the application."""
        self.SetAppName(__app_name__)
        self.SetVendorName(__app_name__)

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

        # Initialize services
        max_concurrent = self._config.get("downloads", "max_concurrent", default=3)
        self._download_manager = DownloadManager(max_concurrent)
        self._download_manager.start()

        rec_dir = self._config.get("recordings", "output_folder", default=self._paths["recordings"])
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
            self._main_window.engine.stop()
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
