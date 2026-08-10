"""Recording scheduler service for managing timed recordings."""

import threading
import logging
from datetime import datetime, timedelta
from typing import Any, Callable

logger = logging.getLogger("radiomaster")


class SchedulerService:
    """Manages recording schedules and executes recordings."""

    def __init__(self, recordings_dir: str) -> None:
        self._recordings_dir = recordings_dir
        self._schedules: list[dict[str, Any]] = []
        self._active_recordings: dict[int, Any] = {}
        self._duration_timers: dict[int, threading.Timer] = {}
        self._running = False
        self._thread: threading.Thread | None = None

        self._on_recording_start: Callable[[int], None] | None = None
        self._on_recording_stop: Callable[[int], None] | None = None

    def start(self) -> None:
        """Start the scheduler monitoring thread."""
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        # Stop all active recordings
        for schedule_id, process in list(self._active_recordings.items()):
            self.stop_recording(schedule_id)

    def add_schedule(self, schedule: dict[str, Any]) -> None:
        """Add a schedule to monitor."""
        self._schedules.append(schedule)

    def remove_schedule(self, schedule_id: int) -> None:
        """Remove a schedule."""
        self._schedules = [s for s in self._schedules if s.get("id") != schedule_id]

    def load_schedules(self, schedules: list[dict[str, Any]]) -> None:
        """Replace the whole monitored schedule list (e.g. from the DB).

        Called at startup and whenever the UI adds/edits/deletes a schedule,
        since the UI only persists to SQLite -- this is what keeps the live
        monitor loop in sync with what's actually been saved.
        """
        self._schedules = list(schedules)

    def start_recording(self, schedule_id: int, url: str, station_name: str,
                        format: str = "auto", duration: int = 0) -> None:
        """Start recording a stream -- uses the same split-track-capable
        RecordingSession as the Radio panel's manual Record button (see
        recording_session.py), instead of the bare `ffmpeg -c copy`
        single-file recording this used to be stuck with regardless of
        Settings > Recordings > "Split recordings into tracks". Confirmed
        live: a scheduled recording never split into per-track files at
        all before this, since nothing here ever looked at that setting
        or watched ICY metadata -- it just copied the raw stream to one
        file until *duration* (or the schedule) ended.

        *duration* is minutes, matching how _detect_conflicts already
        interprets a schedule's duration field -- the previous `-t
        str(duration)` passed it to ffmpeg as raw SECONDS instead, so a
        "record for 60 minutes" schedule was actually only ever
        recording for 60 seconds."""
        from radiomaster.services.recording_session import RecordingSession
        from radiomaster.services.stream_prober import probe_stream_format
        from radiomaster.utils.config import ConfigManager
        config = ConfigManager.get_instance()
        rec_format = format if format and format != "auto" else config.get(
            "recordings.recording_format", default="mp3")
        quality = config.get("recordings.recording_quality", default="320k")
        add_metadata = config.get("recordings.add_metadata", default=True)
        split_tracks = config.get("recordings.split_tracks", default=True)
        match_source = config.get("recordings.match_source_format", default=True)
        source_format = probe_stream_format(url, timeout=6.0) if match_source else None

        def _on_segment(file_path: str, title: str) -> None:
            logger.info(f"Recording segment finalized: {file_path}")

        try:
            session = RecordingSession(
                station_url=url, station_name=station_name, output_dir=self._recordings_dir,
                rec_format=rec_format, quality=quality, add_metadata=add_metadata,
                split_tracks=split_tracks, match_source=match_source, source_format=source_format,
                on_segment_finalized=_on_segment,
            )
            session.start()
            self._active_recordings[schedule_id] = session
            if duration > 0:
                timer = threading.Timer(duration * 60, self.stop_recording, args=(schedule_id,))
                timer.daemon = True
                timer.start()
                self._duration_timers[schedule_id] = timer
            if self._on_recording_start:
                self._on_recording_start(schedule_id)
            logger.info(f"Recording started: {station_name} -> {session.station_dir}")
        except Exception as e:
            logger.error(f"Failed to start recording: {e}")

    def stop_recording(self, schedule_id: int) -> None:
        """Stop an active recording."""
        timer = self._duration_timers.pop(schedule_id, None)
        if timer is not None:
            timer.cancel()
        session = self._active_recordings.pop(schedule_id, None)
        if session:
            session.stop()
            if self._on_recording_stop:
                self._on_recording_stop(schedule_id)

    def _monitor_loop(self) -> None:
        """Monitor loop that checks schedules and starts recordings.
        Also handles auto-download of podcast episodes and conflict detection.
        """
        while self._running:
            now = datetime.now()

            # Check for scheduling conflicts before starting new recordings
            self._detect_conflicts()

            for schedule in self._schedules:
                if not schedule.get("enabled", True):
                    continue

                start_time_str = schedule.get("start_time", "")
                try:
                    start_time = datetime.fromisoformat(start_time_str)
                except (ValueError, TypeError):
                    continue

                if now > start_time + timedelta(minutes=2):
                    last_run = schedule.get("last_run")
                    if not last_run:
                        logger.warning(
                            f"Skipping missed schedule '{schedule.get('title', '')}' "
                            f"from {start_time_str}"
                        )
                    continue

                if start_time <= now <= start_time + timedelta(minutes=1):
                    schedule_id = schedule.get("id", 0)
                    if schedule_id not in self._active_recordings:
                        url = schedule.get("url", "")
                        title = schedule.get("title", "recording")
                        duration = schedule.get("duration", 0)
                        fmt = schedule.get("format", "auto")
                        self.start_recording(schedule_id, url, title, fmt, duration)
                        schedule["last_run"] = now.isoformat()

                        recurrence = schedule.get("recurrence", "")
                        if recurrence:
                            next_start = self._compute_next_recurrence(start_time, recurrence)
                            if next_start:
                                schedule["start_time"] = next_start.isoformat()
                                logger.info(f"Rescheduled '{title}' for {next_start.isoformat()}")

            self._check_auto_downloads()
            threading.Event().wait(30)

    def _detect_conflicts(self) -> None:
        """Detect overlapping recording schedules and log warnings."""
        now = datetime.now()
        active_ranges: list[tuple[datetime, datetime, str]] = []
        for schedule in self._schedules:
            if not schedule.get("enabled", True):
                continue
            try:
                start = datetime.fromisoformat(schedule.get("start_time", ""))
            except (ValueError, TypeError):
                continue
            duration = schedule.get("duration", 0)
            end = start + timedelta(minutes=duration) if duration > 0 else start + timedelta(hours=1)
            title = schedule.get("title", "Unknown")
            # Check against existing active ranges
            for existing_start, existing_end, existing_title in active_ranges:
                if start < existing_end and end > existing_start:
                    logger.warning(
                        f"Schedule conflict: '{title}' ({start}) overlaps with "
                        f"'{existing_title}' ({existing_start}-{existing_end})"
                    )
            active_ranges.append((start, end, title))

    def _check_auto_downloads(self) -> None:
        """Check for podcast episodes to auto-download.

        "Episodes to download per podcast" (podcasts.download_limit) is a
        per-podcast cap -- a single global LIMIT here previously let one
        prolific podcast's backlog crowd out every other podcast's new
        episodes entirely, and ignored the configured limit outright.
        """
        try:
            from radiomaster.utils.config import ConfigManager
            config = ConfigManager.get_instance()
            if not config.get("podcasts.auto_download", default=False):
                return
            download_limit = config.get("podcasts.download_limit", default=3)
            from radiomaster.database.connection import DatabaseManager
            from radiomaster.utils.paths import get_paths
            paths = get_paths()
            db = DatabaseManager(paths["data"])
            db.initialize()
            pending_podcast_ids = db.fetchall(
                "SELECT DISTINCT podcast_id FROM episodes "
                "WHERE download_status = 'none' AND audio_url IS NOT NULL"
            )
            from radiomaster.database.repository import DownloadRepository
            repo = DownloadRepository(db)
            for row in pending_podcast_ids:
                episodes = db.fetchall(
                    "SELECT * FROM episodes WHERE podcast_id = ? AND download_status = 'none' "
                    "AND audio_url IS NOT NULL ORDER BY published_date DESC LIMIT ?",
                    (row["podcast_id"], download_limit),
                )
                for ep in episodes:
                    repo.add(ep.get("audio_url", ""), title=ep.get("title", ""), source_type="podcast")
                    db.execute(
                        "UPDATE episodes SET download_status = 'queued' WHERE id = ?",
                        (ep["id"],),
                    )
            db.commit()
            db.close()
        except Exception as e:
            logger.debug(f"Auto-download check failed: {e}")

    @staticmethod
    def _compute_next_recurrence(current: datetime, recurrence: str) -> datetime | None:
        """Compute the next occurrence for a recurring schedule."""
        r = recurrence.lower()
        if r == "daily":
            return current + timedelta(days=1)
        elif r == "weekly":
            return current + timedelta(weeks=1)
        elif r == "monthly":
            month = current.month + 1
            year = current.year
            if month > 12:
                month = 1
                year += 1
            try:
                return current.replace(year=year, month=month)
            except ValueError:
                return current + timedelta(days=30)
        elif r == "weekdays":
            next_day = current + timedelta(days=1)
            while next_day.weekday() >= 5:  # Saturday=5, Sunday=6
                next_day += timedelta(days=1)
            return next_day
        return None

    def on_recording_start(self, cb: Callable[[int], None]) -> None:
        self._on_recording_start = cb

    def on_recording_stop(self, cb: Callable[[int], None]) -> None:
        self._on_recording_stop = cb
