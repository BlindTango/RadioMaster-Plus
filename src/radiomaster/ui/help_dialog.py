"""Accessible in-app user manual, quick-start guide, and release notes.

Each document uses the same keyboard-friendly topic list and read-only
content pane. Keeping the documentation in the installed application makes
the complete help system available offline and usable with a screen reader.
"""

from __future__ import annotations

import wx

from radiomaster.utils.accessibility import set_accessible_name


def _key(action: str) -> str:
    """A marker resolved from current configuration when a help window opens."""
    return f"{{shortcut:{action}}}"


def render_help_topics(topics: list[tuple[str, str]], config) -> list[tuple[str, str]]:
    """Resolve shortcut markers from the same catalogue used by MainWindow."""
    from radiomaster.ui.shortcut_editor import format_shortcut, load_shortcuts

    shortcuts = load_shortcuts(config)

    def display(action: str) -> str:
        shortcut = shortcuts.get(action, {})
        value = format_shortcut(shortcut)
        if value == "Unassigned":
            return value
        return f"{value} ({'Global' if shortcut.get('global') else 'In app'})"

    panel_actions = (
        ("Radio", "panel_radio"), ("Podcasts", "panel_podcasts"),
        ("Audiobooks", "panel_audiobooks"), ("Media Player", "panel_media"),
        ("YouTube", "panel_youtube"), ("Downloads", "panel_downloads"),
        ("Scheduler", "panel_scheduler"),
    )
    panel_summary = "; ".join(f"{label}: {display(action)}" for label, action in panel_actions)
    rendered = []
    for title, body in topics:
        body = body.replace("{panel_shortcuts}", panel_summary)
        for action in shortcuts:
            body = body.replace(f"{{shortcut:{action}}}", display(action))
        rendered.append((title, body))
    return rendered

USER_MANUAL_TOPICS: list[tuple[str, str]] = [
    ("Welcome and Overview", (
        "RadioMaster+ streams internet radio, podcasts, YouTube videos, audiobooks "
        "(including DAISY), and local media files -- all fully operable by keyboard "
        "and screen reader.\n\n"
        "The main window has seven tabs, reached with the assigned panel shortcuts "
        "({panel_shortcuts}) or by "
        "clicking a tab: Radio, Podcasts, Audiobooks, Media Player, YouTube, Downloads, "
        "and Scheduler. Below the tabs is the transport bar (Play/Pause, Stop, "
        "Next/Previous/First/Last, Volume, Rate, Pan, Record, Mute), which stays the "
        "same across every tab.\n\n"
        "On first launch, RadioMaster+ downloads the Radio Browser station catalog "
        "into a local database (a few seconds, shown in the status bar). After that, "
        "browsing is instant and works offline using the cached copy."
    )),
    ("Main Window and Menus", (
        "The main window is divided into a seven-page listbook, a persistent Now "
        "Playing and transport area, an optional lyrics panel, and a status bar. "
        "Assigned panel shortcuts are {panel_shortcuts}. Use "
        f"{_key('next_tab')} and {_key('previous_tab')} to move forward and backward "
        "through those pages.\n\n"
        "File opens local files, folders, URLs, and podcast OPML files. View "
        "controls the equalizer, lyrics panel, fullscreen mode, theme, and "
        "language. Effects contains live audio effects and preset managers. "
        "Tools contains the sleep timer, downloads, recording scheduler, track "
        "tools, shortcut editors, and Settings. Help contains this manual, the "
        "Quick Start Guide, bundled Release Notes, YouTube library updates, app "
        "updates, and About information.\n\n"
        "Press Alt plus the underlined menu letter to open a menu. Arrow through "
        "items and press Enter to activate one. Escape closes an open menu or "
        "dialog without applying an action."
    )),
    ("Step by Step: Play Your First Station", (
        f"1. Make sure the Radio tab is selected ({_key('panel_radio')}).\n"
        "2. Tab to the station list on the right, or use Search at the top to find "
        "a station by name, genre, country, or language.\n"
        "3. Select a station and press Enter, or double-click it, to start playing.\n"
        "4. Use the transport bar's Volume slider to adjust loudness, or Mute to "
        "silence it without losing your volume level.\n"
        "5. Press Stop when you're done, or just pick another station -- doing so "
        "crossfades into it instead of cutting out, if Crossfade Duration is set "
        "above 0 in Settings > Playback."
    )),
    ("Step by Step: Record a Station", (
        "1. Select or start playing the station you want to record.\n"
        "2. Press the Record button in the transport bar (it changes to show "
        "recording is active).\n"
        "3. Press Record again to stop, or use Tools > Recording Scheduler... to "
        "automate this for future times.\n"
        "4. Recordings are saved to the folder shown in Settings > Recordings > "
        "Recording Location -- in a Portable install this defaults to a data\\ "
        "folder next to the app itself rather than your user profile."
    )),
    ("Step by Step: Subscribe to a Podcast", (
        f"1. Switch to the Podcasts tab ({_key('panel_podcasts')}).\n"
        "2. Use the search box to find a show, or File > Podcasts > Add Feed... to "
        "subscribe directly by RSS URL.\n"
        "3. Select an episode and press Play, or Download Episode to save it for "
        "offline listening (visible afterward in the Downloads tab).\n"
        "4. File > Podcasts > Import/Export OPML moves your whole subscription list "
        "to or from another podcast app."
    )),
    ("Step by Step: Download a YouTube Video", (
        f"1. Switch to the YouTube tab ({_key('panel_youtube')}).\n"
        "2. Search for a video or paste a URL.\n"
        "3. Select a result, choose a quality/format, and press Download Video "
        "(or Download Audio Only for MP3/Opus/FLAC extraction).\n"
        f"4. Track progress in the Downloads tab ({_key('panel_downloads')}) -- downloads are "
        "queue-based and can be paused/resumed."
    )),
    ("Radio Tab", (
        "The Radio tab browses the locally cached Radio Browser catalog by "
        "Favorites, All Stations, Countries, Languages, Genres, and Networks. "
        "Use Search to filter stations, then Enter or double-click to play. Add "
        "Custom Station accepts a name and direct stream URL for stations absent "
        "from the public catalog.\n\n"
        "The station context menu provides Play/Pause/Resume, Stop, Favorites, "
        "Record, Volume, Pan, and Rate commands. Station history supports Previous, "
        "Next, First, and Last. ICY/SHOUTcast metadata updates the now-playing "
        "artist and title when the station supplies it.\n\n"
        "Settings > Radio controls duplicate visibility, stream reconnection, "
        "automatic playback of the last station, and how often the cached station "
        "database refreshes. Update Now refreshes it immediately."
    )),
    ("Podcasts Tab", (
        "The Podcasts tab has category, podcast, and episode lists. Search the "
        "directory or browse categories, select a show, and Subscribe to keep it "
        "in your library. Add RSS Feed subscribes to a feed URL directly.\n\n"
        "Select an episode and press Enter or use its context menu to Play, Pause, "
        "Resume, Stop, Download, or Download All. Playback progress is remembered. "
        "Downloaded episodes appear in Downloads and can be played offline.\n\n"
        "Import OPML and Export OPML transfer subscriptions between podcast apps. "
        "gpodder.net Sync uses the account configured in Settings > Podcasts. That "
        "settings page also controls storage, automatic downloads, refresh "
        "frequency, retention, and auto-advance."
    )),
    ("Audiobooks Tab", (
        "Browse File opens one audiobook media file. Browse Folder opens a conventional "
        "audiobook folder or a DAISY 2.02 or DAISY NISO 39.86 book. The library tree "
        "lists loaded books and the chapter "
        "list provides direct chapter navigation. Select a chapter and press Enter "
        "for recorded audio, then use the transport controls for playback. Use "
        "Read with TTS for SAPI text-to-speech.\n\n"
        "Add Bookmark stores the current location. RadioMaster+ also remembers the "
        "last position automatically and offers to resume it. For DAISY books, "
        "narrated audio and text remain synchronized and the current sentence can "
        "be highlighted."
    )),
    ("Media Player Tab", (
        "Use File > Open File, File > Open Folder, or Add to Playlist to add local "
        "audio and video. The playlist shows the queued files; select one and press "
        "Enter or double-click it, then use the transport controls for playback. "
        "Clear removes the current playlist without deleting files from disk.\n\n"
        "Supported formats are provided by FFmpeg and include MP3, FLAC, OGG, WAV, "
        "AAC, M4A, Opus, M4B, MP4, MKV, AVI, WebM, and MOV. Metadata tags supply "
        "artist and title information when available. Track changes can crossfade "
        "according to Settings > Playback."
    )),
    ("YouTube Tab", (
        "Search can return Videos, Channels, or Playlists. Activating a video plays "
        "it; activating a channel or playlist opens its videos. Subscribe to "
        "Channel stores a channel in the left-hand subscriptions list. Play URL "
        "accepts a YouTube or other yt-dlp-supported page URL.\n\n"
        "Playback prepares and merges the best available separate video and audio "
        "streams. This preserves source quality but a long or 4K video can take "
        "time and temporary disk space before its window opens. If that preparation "
        "fails, RadioMaster+ falls back to a directly playable combined stream.\n\n"
        "Download saves video at Best, 1080p, 720p, 480p, or 360p. Download Audio "
        "extracts MP3, Opus, FLAC, or M4A using the audio quality configured in "
        "Settings > Downloads. Use Help > Update YouTube Library if YouTube changes "
        "cause searches, playback, or downloads to stop working."
    )),
    ("Downloads Tab", (
        "Active Downloads and Recordings lists work currently in progress. Stop "
        "Recording ends an active recording; Remove removes an item from the list. "
        "The context menu can also restart supported work.\n\n"
        "Download History contains completed, failed, and stopped items. Play opens "
        "a completed file, Retry resubmits a failed item, and Remove removes its "
        "history entry. Removing a list entry does not silently delete an unrelated "
        "source file. Refresh reloads both lists from the database."
    )),
    ("Scheduler Tab", (
        "The Scheduler tab lists planned recordings with station, start time, "
        "duration, recurrence, format, and enabled state. Add Schedule creates one; "
        "Edit changes the selected schedule; Delete removes it after confirmation. "
        "The same feature is available from Tools > Recording Scheduler.\n\n"
        "Schedules can be one-time or recurring. Recordings run independently of "
        "the station currently playing, and multiple compatible recordings may run "
        "at the same time. Confirm the Windows clock, output folder, free disk "
        "space, and network availability before relying on an unattended schedule."
    )),
    ("Step by Step: Read/Listen to an Audiobook", (
        f"1. Switch to the Audiobooks tab ({_key('panel_audiobooks')}) and browse to a DAISY 2.02 or "
        "NISO 39.86 book folder, or a folder of conventional audio files.\n"
        "2. Use the chapter list to jump to any chapter -- audio and text stay "
        "synchronized, with the current sentence highlighted as it plays.\n"
        "3. If a book has no narrated audio, SAPI Text-to-Speech reads it aloud "
        "instead, using the voice configured in Settings.\n"
        "4. Your position is bookmarked automatically; reopening the book resumes "
        "where you left off."
    )),
    ("Transport Bar & Playback Controls", (
        "First/Rewind/Previous/Play-Pause/Stop/Next/Fast-Forward/Last mirror a "
        "typical media player, plus:\n\n"
        "Volume, Rate (0.5x-3.0x), and Pan all change live during playback -- no "
        "restart, no reconnect -- for radio, podcasts, audiobooks, local audio, and "
        "YouTube audio. Video playback still restarts on these changes since it goes "
        "through a separate rendering path (ffplay).\n\n"
        "Volume, Rate, and Pan are remembered between sessions and restored "
        "automatically the next time you launch the app.\n\n"
        "Fast Forward/Rewind and the position slider are only enabled for seekable "
        "content -- live radio streams have no fixed timeline, so they stay greyed "
        "out during radio playback (this is correct, not a bug)."
    )),
    ("Crossfade", (
        "Switching radio stations, or moving to the next track in the Media Player "
        "tab's playlist, crossfades between the outgoing and incoming audio instead "
        "of cutting directly -- two real audio streams overlap and blend for the "
        "duration configured in Settings > Playback > Crossfade Duration (seconds). "
        "Setting it to 0 disables crossfade and switches instantly instead."
    )),
    ("The Effects Menu", (
        "The Effects menu has one submenu per effect: Echo, Equalizer, Reverb, "
        "Dynamic Range, Pitch/Tempo Shift, Chorus, Compressor, Distortion, Flanger, "
        "and Gargle. Each submenu has:\n\n"
        "On/Off -- a checkable toggle enabling that effect on the live playback "
        "stream.\n\n"
        "A list of built-in presets -- click one to apply it immediately (this also "
        "turns the effect on).\n\n"
        "A Preset Manager -- full create/edit/rename/delete for your own custom "
        "presets, built starting from any existing preset's values. Built-in "
        "presets can't be edited or deleted, but can be used as a starting point "
        "for a new custom one.\n\n"
        "Reverb and Gargle are approximations: Reverb layers several echo taps to "
        "simulate room reflections (there's no dedicated reverb filter available), "
        "and Gargle uses amplitude modulation (tremolo) rather than a literal "
        "gargle effect -- both documented as such in the code."
    )),
    ("Recording Scheduler", (
        "Tools > Recording Scheduler... schedules automatic recordings: one-time, "
        "daily, weekly, or recurring. Pick a station, a start time, a duration, and "
        "an output format. Multiple recordings can run simultaneously, independent "
        "of what you're currently listening to."
    )),
    ("Downloads", (
        f"The Downloads tab ({_key('panel_downloads')}) shows every queued, in-progress, and completed "
        "download from Podcasts and YouTube in one place, with pause/resume and "
        "history. Download location, format, and metadata embedding are configured "
        "in Settings > Downloads."
    )),
    ("Lyrics Panel", (
        f"View > Toggle Lyrics Panel ({_key('toggle_lyrics')}) shows or hides lyrics for the current "
        "track. RadioMaster+ can query LRCLib, Lyrics.ovh, Genius, and Musixmatch, "
        "then caches successful results locally. Synced LRC lyrics highlight the "
        "current line during playback; plain lyrics remain readable without timed "
        "highlighting.\n\n"
        "Accurate artist and title metadata gives the best lookup results. Radio "
        "stations must publish current-track metadata; local files should have "
        "useful tags. A failed lookup does not prevent playback."
    )),
    ("Track Identifier and Track Splitter", (
        "Tools > Track Identifier fingerprints an audio sample with AcoustID and "
        "looks up matching MusicBrainz metadata. Deezer lookup is also available "
        "where configured. Internet access is required and recognition is not "
        "guaranteed for speech, noisy recordings, or obscure music.\n\n"
        "Tools > Split Track divides a mixed recording into tracks and can apply "
        "identified metadata and filename templates. Always choose a separate "
        "output folder when you want to preserve the original recording untouched."
    )),
    ("Sleep Timer", (
        f"Tools > Sleep Timer ({_key('sleep_timer')}) can stop playback after a countdown, at the "
        "end of the current track, or at the end of the playlist. Review the active "
        "timer before leaving the computer unattended. Starting a replacement timer "
        "supersedes the previous timer."
    )),
    ("Keyboard Shortcuts", (
        f"Tools > Keyboard Shortcuts... ({_key('keyboard_shortcuts')}) lets you view and rebind menu, "
        "panel, and playback actions in one accessible list. Use New, Edit, or "
        "Delete to manage an assignment. Check Global shortcut while creating or "
        "editing an assignment when it should work even while RadioMaster+ is not "
        "focused. Leave it unchecked for an in-app shortcut. Conflicts are rejected "
        "before you can save."
    )),
    ("Default Keyboard Navigation", (
        "Panel shortcuts: {panel_shortcuts}.\n"
        f"{_key('next_tab')}: next panel. {_key('previous_tab')}: previous panel.\n"
        f"{_key('play_pause')}: play or pause. {_key('stop')}: stop.\n"
        f"{_key('search')}: focus search.\n"
        f"{_key('open_file')}: open a file. {_key('open_url')}: open a URL.\n"
        f"{_key('toggle_lyrics')}: toggle lyrics. {_key('toggle_fullscreen')}: toggle fullscreen.\n"
        f"{_key('download_manager')}: Downloads. {_key('recording_scheduler')}: Scheduler. "
        f"{_key('track_identifier')}: Track Identifier.\n"
        f"{_key('sleep_timer')}: Sleep Timer. {_key('keyboard_shortcuts')}: Keyboard Shortcuts. "
        f"{_key('settings')}: Settings.\n"
        f"{_key('user_manual')}: User Manual. {_key('exit')}: exit.\n\n"
        "Lists use Up/Down, Home/End, Page Up/Page Down, and Enter in the normal "
        "Windows manner. Tab and Shift+Tab move between controls. Context Menu or "
        "Shift+F10 opens an item's available commands. User-rebound shortcuts can "
        "replace several defaults, so consult Tools > Keyboard Shortcuts if a key "
        "does not perform the action shown here."
    )),
    ("Settings", (
        f"Tools > Settings... ({_key('settings')}) covers 9 categories: General, Playback, "
        "Radio, Podcasts, Downloads, Recordings, Network, Accessibility, and "
        "Advanced (logging level and log file location).\n\n"
        "Notable options: default volume/rate, crossfade duration, output audio "
        "device, ReplayGain, station database update behavior, proxy/network "
        "settings, download/recording folders, and whether to check for app "
        "updates automatically on startup.\n\n"
        "Press Apply or OK to save changes -- most settings, including theme and "
        "accessibility options, apply immediately without restarting."
    )),
    ("Accessibility Notes", (
        "Every control has an explicit accessible name read by NVDA/Narrator, "
        "including composite controls like the search box's inner text field. Full "
        "keyboard navigation is supported throughout -- every feature, including "
        "the Effects menu's Preset Manager and Keyboard Shortcuts editor, is "
        "reachable without a mouse.\n\n"
        "High Contrast mode (Settings > Accessibility) respects Windows' system "
        "high-contrast setting, and a dyslexia-friendly font option (OpenDyslexic) "
        "is available for anyone who has it installed.\n\n"
        "If you find a control a screen reader doesn't announce correctly, that's "
        "a bug worth reporting -- note exactly what you heard (or didn't)."
    )),
    ("Checking for Updates", (
        "Help > Check for Updates... checks GitHub for a newer release right away "
        "and shows the release notes plus a Download & Install button if one is "
        "found.\n\n"
        "By default RadioMaster+ also checks automatically, silently, once at "
        "startup -- this can be turned off in Settings > Advanced > Check for "
        "updates on startup. A silent check that finds nothing new, or fails (e.g. "
        "no internet connection), stays quiet; only a manual check reports "
        "'you're up to date' or an error.\n\n"
        "Choosing Download & Install downloads the installer, then closes "
        "RadioMaster+ and launches it -- follow its prompts to finish updating."
    )),
    ("Portable Mode", (
        "If RadioMaster+ was installed in Portable mode, all of its data -- "
        "settings, the station database, downloads, recordings, and logs -- lives "
        "in a data\\ folder next to the application itself, not in your Windows "
        "user profile. This means the whole install folder can be copied to a USB "
        "drive or another PC and it keeps working with everything intact, and "
        "uninstalling is as simple as deleting the folder."
    )),
    ("Files, Storage, and Backups", (
        "RadioMaster+ stores settings, its SQLite database, logs, cached lyrics, "
        "subscriptions, schedules, and history in its writable data location. In a "
        "portable installation that is the data folder beside the application. In "
        "a protected installation such as Program Files, per-user application data "
        "is used instead.\n\n"
        "Downloads and recordings can consume substantial space. Their locations "
        "are configurable in Settings. To back up your setup, close RadioMaster+ "
        "first and copy the complete data folder plus any download and recording "
        "folders you want to preserve."
    )),
    ("Troubleshooting", (
        "No sound: confirm the Now Playing state and volume, unmute, then check "
        "Settings > Playback > Output Device. A disconnected saved device falls "
        "back to the Windows default for that session.\n\n"
        "A radio station will not play: try another station, refresh the station "
        "database, and verify proxy settings. Public station URLs sometimes expire.\n\n"
        "YouTube fails: use Help > Update YouTube Library, retry, and confirm there "
        "is enough temporary disk space for best-quality playback. Some videos are "
        "private, age-restricted, region-restricted, or unavailable.\n\n"
        "A download or recording fails: open Downloads, review its state, retry, "
        "and confirm the destination exists and is writable.\n\n"
        "The interface behaves unexpectedly: restart the app, then inspect the log "
        "location shown in Settings > Advanced. When reporting a bug, include the "
        "RadioMaster+ version from Help > About, the exact action, expected result, "
        "actual result, and relevant log lines."
    )),
    ("Hardware & System Requirements", (
        "Operating System: Windows 10 or later (64-bit).\n\n"
        "Processor: Any CPU from the last decade is sufficient for audio playback "
        "and streaming. Video playback and YouTube downloads benefit from a modern "
        "multi-core CPU, since video decoding and yt-dlp extraction are more "
        "demanding than audio alone.\n\n"
        "Memory: 4 GB RAM minimum, 8 GB recommended -- the station database, audio "
        "decoding, and (if used) local Text-to-Speech voices all share memory with "
        "the rest of the system.\n\n"
        "Storage: About 700 MB for the application itself (it bundles ffmpeg, "
        "ffplay, ffprobe, and yt-dlp so no separate installs are needed), plus "
        "whatever space you want for downloaded audio/video, podcast episodes, and "
        "recordings -- these can add up quickly and are entirely up to you to "
        "manage.\n\n"
        "Audio: Any Windows-compatible sound output device (WASAPI). Multiple "
        "output devices can be selected in Settings > Playback.\n\n"
        "Network: An internet connection is required for streaming radio/YouTube, "
        "podcast/station directory browsing, downloading, checking for updates, "
        "and metadata/lyrics lookups. Local file playback, audiobook reading, and "
        "already-downloaded content all work fully offline.\n\n"
        "Screen Reader: NVDA is the primary screen reader this app is developed "
        "and tested against; Windows Narrator is also supported through the same "
        "standard accessibility APIs."
    )),
]


QUICK_START_TOPICS: list[tuple[str, str]] = [
    ("Five-Minute Quick Start", (
        "1. Use an assigned panel shortcut to choose a main tab: {panel_shortcuts}.\n"
        "2. On Radio, select a station and press Enter. On Podcasts or YouTube, "
        "search first, select a result, and press Enter.\n"
        f"3. Use {_key('play_pause')} to play or pause and {_key('stop')} to stop. Tab to the Now "
        "Playing controls for Volume, Rate, Pan, seeking, recording, and track "
        "navigation.\n"
        f"4. Press {_key('settings')} to review output device, downloads, recordings, network, "
        "accessibility, and update settings.\n"
        f"5. Press {_key('user_manual')} at any time for the complete User Manual."
    )),
    ("Play Internet Radio", (
        f"Press {_key('panel_radio')}. Tab to Search and type a station name, genre, country, or "
        "language, or browse the category tree. Select a station in the results "
        "list and press Enter. Use the context menu to add it to Favorites or start "
        "recording."
    )),
    ("Play Podcasts, Local Media, and Audiobooks", (
        f"Podcasts: press {_key('panel_podcasts')}, search or choose a subscription, select an episode, "
        f"and press Enter. Audiobooks: press {_key('panel_audiobooks')}, choose Browse Folder, select a "
        f"chapter, then Play or Read with TTS. Local media: press {_key('open_file')} for a file "
        "or use File > Open Folder, then select a playlist item and press Enter."
    )),
    ("Play YouTube", (
        f"Press {_key('panel_youtube')}, enter a search, choose Videos, Channels, or Playlists, and "
        "activate a result. RadioMaster+ prepares the best available video and audio "
        "before opening playback, so large or 4K videos can take longer to start. "
        "Use Help > Update YouTube Library if extraction stops working."
    )),
    ("Accessibility Essentials", (
        "Tab and Shift+Tab move between controls. Arrow keys move in lists and "
        "menus, Enter activates, Shift+F10 opens a context menu, and Escape backs "
        f"out. {_key('next_tab')} changes main tabs. Tools > Keyboard Shortcuts manages both "
        "in-app and optional global keys from one accessible list. "
        "Settings > Accessibility contains high contrast, dyslexia font, screen "
        "reader optimization, enhanced keyboard navigation, focus indicators, and "
        "reduced motion."
    )),
]


RELEASE_NOTES_TOPICS: list[tuple[str, str]] = [
    ("Version 1.1.66", (
        "Streamlined the Scheduler panel by removing its redundant date and time "
        "controls; scheduling details remain in the Add and Edit dialogs.\n\n"
        "Removed redundant Play buttons from Audiobooks and Media Player. Press "
        "Enter or double-click a chapter or playlist item to start it, then use "
        "the shared transport controls. Audiobooks now has a Browse File button "
        "for loading an individual media file.\n\n"
        "Fixed File > Open Folder in Media Player so supported files, including "
        "files in subfolders, appear in the playlist and are ready for playback."
    )),
    ("Version 1.1.65", (
        "Replaced the Scheduler panel's inaccessible calendar grid with labeled "
        "native date and time pickers. The selected values now prefill new "
        "schedules, which default five minutes ahead, and enabled schedules "
        "cannot be saved with a start time in the past.\n\n"
        "Fixed the Keyboard Shortcuts assignment dialog leaving its Create or "
        "Save button disabled after entering a new binding. The action remains "
        "available and now presents a clear validation message with focus "
        "returned to the field that needs correction."
    )),
    ("Version 1.1.64", (
        "Fixed portable installations losing their configured downloads, "
        "recordings, and podcast folders when a removable drive receives a "
        "different drive letter. Application-owned locations are now stored "
        "relative to the RadioMaster+ folder and resolved against its current "
        "location at runtime.\n\n"
        "Existing absolute portable paths are migrated automatically, including "
        "completed-download file locations and retry folders, while deliberately "
        "selected folders outside RadioMaster+ remain absolute."
    )),
    ("Version 1.1.63", (
        "Expanded the Keyboard Shortcuts main-key catalogue with multimedia "
        "playback and volume keys, browser controls, application-launch keys, "
        "F1 through F24, lock/state keys, extended numpad navigation, context-menu "
        "and other wxPython-representable special keys.\n\n"
        "The new keys work with both in-app accelerators and supported Windows "
        "global assignments. The assignment dialog now explains that Fn is "
        "processed by keyboard firmware and cannot be detected as a standalone "
        "modifier; users should select the resulting media or function key instead."
    )),
    ("Version 1.1.62", (
        "Redesigned Keyboard Shortcuts as an accessible, searchable CRUD manager "
        "covering menus, panels, effects, and playback controls. Added explicit "
        "main-key and left/right modifier selection, duplicate prevention, and "
        "immediate application of saved assignments.\n\n"
        "Consolidated global hotkeys into the same editor with a per-assignment "
        "Global shortcut checkbox, scope column, Windows-key support for global "
        "assignments, and one authoritative command catalogue.\n\n"
        "The User Manual and Quick Start Guide now resolve every documented "
        "shortcut dynamically, including its Global or In-app scope, so help "
        "always reflects the current saved configuration."
    )),
    ("Version 1.1.61", (
        "Added a comprehensive offline User Manual covering every main tab, menus, "
        "playback, effects, recording, downloads, lyrics, track tools, settings, "
        "shortcuts, accessibility, storage, updates, and troubleshooting.\n\n"
        "Added dedicated Quick Start Guide and bundled Release Notes views. "
        "Reorganized Help so User Manual is first, Check for Updates is second-last, "
        "and About RadioMaster+ is last. The topic-list and read-only content design "
        "remains fully keyboard and screen-reader accessible."
    )),
    ("Version 1.1.60", (
        "YouTube playback now prioritizes the best available separate video and "
        "audio streams, merges them without re-encoding, and downloads four media "
        "fragments concurrently while preparing playback. The previous combined "
        "stream remains as a fallback. Large and 4K videos may therefore take "
        "longer to start but play at substantially better source quality.\n\n"
        "This release also adds a regression test for adaptive format selection."
    )),
    ("Version 1.1.59", (
        "Fixed search-result activation so Enter and double-click play the row the "
        "user actually activated. Removed the redundant second video window; FFplay "
        "now provides the single playback window."
    )),
    ("Version 1.1.58", (
        "Removed obsolete playback-controls and playlist-widget implementations "
        "that were no longer used by the application."
    )),
    ("Version 1.1.57", (
        "Updated yt-dlp, added reliable temporary-file playback fallback for split "
        "video/audio streams, and added manual and scheduled YouTube library updates."
    )),
]


class HelpDialog(wx.Dialog):
    def __init__(self, parent: wx.Window, *, title: str = "RadioMaster+ User Manual",
                 topics: list[tuple[str, str]] | None = None, config=None) -> None:
        super().__init__(parent, title=title,
                          size=(780, 520), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        source_topics = topics if topics is not None else USER_MANUAL_TOPICS
        active_config = config if config is not None else getattr(parent, "_config", None)
        self._topics = (
            render_help_topics(source_topics, active_config) if active_config is not None else source_topics
        )

        topics_label = wx.StaticText(self, label="&Topics:")
        self.topic_list = wx.ListBox(self, choices=[topic for topic, _ in self._topics])
        set_accessible_name(self.topic_list, "Help Topics")

        content_label = wx.StaticText(self, label="Content:")
        self.content = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_BESTWRAP,
        )
        set_accessible_name(self.content, "Help Content")

        close_btn = wx.Button(self, wx.ID_OK, label="&Close")

        left = wx.BoxSizer(wx.VERTICAL)
        left.Add(topics_label, 0, wx.BOTTOM, 4)
        left.Add(self.topic_list, 1, wx.EXPAND)

        right = wx.BoxSizer(wx.VERTICAL)
        right.Add(content_label, 0, wx.BOTTOM, 4)
        right.Add(self.content, 1, wx.EXPAND)

        body = wx.BoxSizer(wx.HORIZONTAL)
        body.Add(left, 0, wx.EXPAND | wx.ALL, 10)
        body.Add(right, 1, wx.EXPAND | wx.TOP | wx.BOTTOM | wx.RIGHT, 10)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(body, 1, wx.EXPAND)
        outer.Add(close_btn, 0, wx.ALIGN_CENTER | wx.BOTTOM, 10)
        self.SetSizer(outer)

        self.topic_list.Bind(wx.EVT_LISTBOX, self._on_topic_selected)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_OK))

        self.topic_list.SetSelection(0)
        self._show_topic(0)
        # A plain SetFocus() here gets overridden once ShowModal() gives the
        # default (Close) button initial focus -- EVT_INIT_DIALOG fires
        # after that, so setting focus there sticks.
        self.Bind(wx.EVT_INIT_DIALOG, self._on_init_dialog)

    def _on_init_dialog(self, event: wx.InitDialogEvent) -> None:
        event.Skip()
        self.topic_list.SetFocus()

    def _on_topic_selected(self, event: wx.CommandEvent) -> None:
        self._show_topic(self.topic_list.GetSelection())

    def _show_topic(self, index: int) -> None:
        if 0 <= index < len(self._topics):
            title, body = self._topics[index]
            self.content.ChangeValue(f"{title}\n{'=' * len(title)}\n\n{body}")
