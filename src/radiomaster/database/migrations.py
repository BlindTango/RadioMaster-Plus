"""Database schema migrations for RadioMaster+."""

import sqlite3

MIGRATIONS: list[tuple[int, str]] = [
    (1, """
        CREATE TABLE IF NOT EXISTS stations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id TEXT UNIQUE,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            country TEXT,
            country_code TEXT,
            language TEXT,
            language_codes TEXT,
            genre TEXT,
            tags TEXT,
            bitrate INTEGER,
            codec TEXT,
            votes INTEGER DEFAULT 0,
            clicks INTEGER DEFAULT 0,
            last_updated TEXT,
            is_custom INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """),
    (2, """
        CREATE TABLE IF NOT EXISTS station_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            station_id TEXT NOT NULL,
            category_type TEXT NOT NULL,
            category_value TEXT NOT NULL
        );
    """),
    (3, """
        CREATE TABLE IF NOT EXISTS podcasts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            feed_url TEXT UNIQUE NOT NULL,
            title TEXT,
            description TEXT,
            author TEXT,
            artwork_url TEXT,
            website_url TEXT,
            is_custom INTEGER DEFAULT 0,
            last_updated TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """),
    (4, """
        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            podcast_id INTEGER NOT NULL,
            guid TEXT UNIQUE,
            title TEXT,
            description TEXT,
            content_encoded TEXT,
            duration INTEGER,
            published_date TEXT,
            audio_url TEXT,
            file_path TEXT,
            download_status TEXT DEFAULT 'none',
            play_position REAL DEFAULT 0,
            is_played INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (podcast_id) REFERENCES podcasts(id) ON DELETE CASCADE
        );
    """),
    (5, """
        CREATE TABLE IF NOT EXISTS audiobooks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            author TEXT,
            narrator TEXT,
            duration REAL DEFAULT 0,
            format TEXT,
            file_path TEXT,
            folder_path TEXT,
            cover_path TEXT,
            chapters TEXT,
            last_position REAL DEFAULT 0,
            bookmarks TEXT,
            is_daisy INTEGER DEFAULT 0,
            daisy_format TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """),
    (6, """
        CREATE TABLE IF NOT EXISTS media_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE,
            title TEXT,
            artist TEXT,
            album TEXT,
            duration REAL DEFAULT 0,
            format TEXT,
            bitrate INTEGER,
            cover_path TEXT,
            last_position REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """),
    (7, """
        CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """),
    (8, """
        CREATE TABLE IF NOT EXISTS playlist_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id INTEGER NOT NULL,
            item_type TEXT NOT NULL,
            item_id INTEGER,
            item_url TEXT,
            title TEXT,
            duration REAL DEFAULT 0,
            position INTEGER DEFAULT 0,
            FOREIGN KEY (playlist_id) REFERENCES playlists(id) ON DELETE CASCADE
        );
    """),
    (9, """
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            title TEXT,
            source_type TEXT,
            format TEXT,
            quality TEXT,
            file_path TEXT,
            status TEXT DEFAULT 'queued',
            progress REAL DEFAULT 0,
            total_size INTEGER,
            error TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """),
    (10, """
        CREATE TABLE IF NOT EXISTS schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            title TEXT,
            source_type TEXT,
            start_time TEXT NOT NULL,
            duration INTEGER,
            recurrence TEXT,
            format TEXT DEFAULT 'auto',
            enabled INTEGER DEFAULT 1,
            last_run TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """),
    (11, """
        CREATE TABLE IF NOT EXISTS recordings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            schedule_id INTEGER,
            url TEXT,
            title TEXT,
            file_path TEXT,
            duration REAL,
            format TEXT,
            size_bytes INTEGER,
            recorded_at TEXT DEFAULT (datetime('now'))
        );
    """),
    (12, """
        CREATE TABLE IF NOT EXISTS track_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT,
            artist TEXT,
            title TEXT,
            album TEXT,
            duration REAL,
            source TEXT,
            raw_data TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """),
    (13, """
        CREATE TABLE IF NOT EXISTS lyrics_cache (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artist TEXT NOT NULL,
            title TEXT NOT NULL,
            lyrics TEXT,
            source TEXT,
            is_synced INTEGER DEFAULT 0,
            lrc_data TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(artist, title)
        );
    """),
    (14, """
        CREATE TABLE IF NOT EXISTS keyboard_shortcuts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_name TEXT UNIQUE NOT NULL,
            primary_key TEXT,
            secondary_key TEXT,
            description TEXT
        );
    """),
    (15, """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """),
    (16, """
        CREATE TABLE IF NOT EXISTS search_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            source_type TEXT,
            searched_at TEXT DEFAULT (datetime('now'))
        );
    """),
    (17, """
        CREATE TABLE IF NOT EXISTS play_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            source_id INTEGER,
            title TEXT,
            artist TEXT,
            url TEXT,
            position REAL DEFAULT 0,
            duration REAL DEFAULT 0,
            played_at TEXT DEFAULT (datetime('now'))
        );
    """),
    (18, """
        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            audiobook_id INTEGER,
            position REAL NOT NULL,
            label TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (audiobook_id) REFERENCES audiobooks(id) ON DELETE CASCADE
        );
    """),
    (19, """
        CREATE TABLE IF NOT EXISTS custom_stations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            genre TEXT,
            country TEXT,
            language TEXT,
            tags TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """),
    (20, """
        CREATE TABLE IF NOT EXISTS sleep_timers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_time TEXT NOT NULL,
            duration INTEGER DEFAULT 0,
            mode TEXT DEFAULT 'countdown',
            enabled INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """),
    # BookmarkRepository (used by audiobook_panel.py) reads/writes
    # title/source_type/url/notes columns that migration 18 never created --
    # every bookmark.add() call has been failing with "no such column" since
    # the feature was introduced. Add the missing columns; audiobook_id/label
    # are left in place, unused but harmless.
    (21, """
        ALTER TABLE bookmarks ADD COLUMN title TEXT DEFAULT '';
        ALTER TABLE bookmarks ADD COLUMN source_type TEXT DEFAULT '';
        ALTER TABLE bookmarks ADD COLUMN url TEXT DEFAULT '';
        ALTER TABLE bookmarks ADD COLUMN notes TEXT DEFAULT '';
    """),
    # DownloadManager.add_download()'s output_dir/extract_audio/
    # filename_base were only ever passed in-memory at request time and
    # never persisted -- so a download that needed retrying (stalled,
    # failed, or orphaned by an app restart -- see DownloadRepository.
    # fail_orphaned/retry) had no way to be correctly re-submitted: the
    # row remembered *what* to download but not *how*. audio_quality
    # isn't stored separately since it's always deterministically
    # re-derivable from the existing quality column (see youtube_panel.py).
    (22, """
        ALTER TABLE downloads ADD COLUMN output_dir TEXT DEFAULT '';
        ALTER TABLE downloads ADD COLUMN extract_audio INTEGER DEFAULT 0;
        ALTER TABLE downloads ADD COLUMN filename_base TEXT DEFAULT '';
    """),
]


def run_migrations(conn: sqlite3.Connection) -> None:
    """Run all pending database migrations."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER PRIMARY KEY)"
    )
    current_version = conn.execute(
        "SELECT MAX(version) FROM schema_version"
    ).fetchone()[0] or 0

    for version, sql in MIGRATIONS:
        if version > current_version:
            conn.executescript(sql)
            conn.execute("INSERT INTO schema_version (version) VALUES (?)", (version,))
    conn.commit()
