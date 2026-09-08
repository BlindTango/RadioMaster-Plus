"""Accessible in-app user manual, quick-start guide, and release notes.

Each document uses the same keyboard-friendly topic list and read-only
content pane. Keeping the documentation in the installed application makes
the complete help system available offline and usable with a screen reader.
"""

from __future__ import annotations

import wx

from radiomaster.utils.accessibility import set_accessible_name
from radiomaster.ui.user_manual import (
    CATEGORY_ORDER as _CATEGORY_ORDER,
    TOPIC_CATEGORIES as _TOPIC_CATEGORIES,
    USER_MANUAL_TOPICS,
)


def _key(action: str) -> str:
    """A marker resolved from current configuration when a help window opens."""
    return f"{{shortcut:{action}}}"


def render_help_topics(topics: list[tuple[str, str]], config) -> list[tuple[str, str]]:
    """Resolve shortcut markers from the same catalogue used by MainWindow."""
    from radiomaster.ui.shortcut_editor import DEFAULT_SHORTCUTS, format_shortcut, load_shortcuts

    shortcuts = load_shortcuts(config) if config is not None else DEFAULT_SHORTCUTS

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
    reference = []
    previous_category = None
    for action, definition in DEFAULT_SHORTCUTS.items():
        category = definition["category"]
        if category != previous_category:
            reference.append(f"\n{category}")
            previous_category = category
        reference.append(f"{definition['description']}: {display(action)}")
    rendered = []
    for title, body in topics:
        body = body.replace("{panel_shortcuts}", panel_summary)
        body = body.replace("{shortcut_reference}", "\n".join(reference).strip())
        for action in shortcuts:
            body = body.replace(f"{{shortcut:{action}}}", display(action))
        rendered.append((title, body))
    return rendered

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
        "language, or choose a browsing section and group. Select a station in the results "
        "list and press Enter. Use the context menu to add it to Favorites or start "
        "recording."
    )),
    ("Play Podcasts, Local Media, and Audiobooks", (
        f"Podcasts: press {_key('panel_podcasts')}, search or choose a subscription, select an episode, "
        f"and press Enter. Audiobooks: press {_key('panel_audiobooks')}, choose Browse Folder, select a "
        f"chapter, then press Enter. Read with TTS works for DAISY chapters containing text. "
        f"Local media: press {_key('open_file')} for a file "
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
        "Settings > Accessibility contains black-and-white high contrast, an "
        "OpenDyslexic font option, concise screen-reader status announcements, F6 and "
        "Shift+F6 region navigation, enhanced focus highlighting, and reduced-motion "
        "startup. Standard labels, Tab navigation, and native focus remain available "
        "regardless of those extra options."
    )),
]


RELEASE_NOTES_TOPICS: list[tuple[str, str]] = [
    ("Version 1.1.81", (
        "Settings now includes an Audiobooks category with Windows SAPI 5 engine "
        "and installed voice selection, speech rate, volume, and voice preview. "
        "Apply or OK saves these choices for the next Read with TTS. The Audiobooks "
        "panel also provides Stop TTS. Speech completion is monitored on the UI "
        "thread for reliable SAPI operation.\n\n"
        "The User Manual has been rewritten into 15 categories covering panels, "
        "playback, effects, tools, settings, and accessibility. It includes the "
        "new Audiobooks settings and a shortcut reference based on current commands."
    )),
    ("Version 1.1.80", (
        "The User Manual's topic list is now a tree: Getting Started, Tabs and "
        "Panels, Playback and Effects, Tools, Settings and Accessibility, and "
        "System and Maintenance appear as expandable branches with the "
        "individual topics as their children, so related topics sit together "
        "instead of one long flat list. The Quick Start Guide and Release Notes "
        "keep their flat lists. Arrows walk the tree, Right or Enter expands a "
        "branch, and selecting a topic shows its content as before.\n\n"
        "Download History on the Downloads tab now honors a configurable entry "
        "count: Settings > Downloads adds Download History entries to show, "
        "which accepts -1 for unlimited. The previous fixed 50-entry cap hid "
        "older downloads with no way to see them."
    )),
    ("Version 1.1.79", (
        "Fixed the Station Health Check freezing the interface during a scan. "
        "The results list now appends only newly found problem stations instead "
        "of rebuilding the entire list every half second, and the dialog's "
        "catalog lookups (opening the dialog, starting a scan, hiding all dead "
        "stations, and playing a result) moved off the interface thread. A scan "
        "over a large catalog now leaves the interface fully responsive."
    )),
    ("Version 1.1.78", (
        "The Podcasts settings' Episodes to download per podcast now accepts -1 "
        "for unlimited: every pending episode of each podcast gets queued for "
        "auto-download instead of only the newest few. The spinner's label and "
        "accessible name document the -1 value."
    )),
    ("Version 1.1.77", (
        "Added Tools > Station Health Check: a background scan of the entire station "
        "catalog that reports dead streams, station names that differ from the "
        "stream's own metadata, websites that no longer resolve, geo-blocked stations "
        "with their home country, and streams whose actual codec, sample rate, "
        "channels, or bitrate differ from the database's claims. Broken stations can "
        "be hidden from all browse lists (reversible via Manage Hidden, and hiding "
        "survives catalog updates). The scan never probes the station you are "
        "listening to or recording, pauses while playback is buffering, and keeps "
        "running if you close its dialog.\n\n"
        "Podcast directory searches now return every result the directories provide "
        "(up to 200 per directory instead of 25), and YouTube searches return up to "
        "100 results for videos, channels, and playlists instead of 20. Stream open "
        "failures now explain themselves in plain language instead of a raw BASS "
        "error number."
    )),
    ("Version 1.1.76", (
        "Effect parameter sliders now update the active BASS effect in real time for "
        "chorus, echo, flanger, gargle, compressor, and distortion, not just reverb -- "
        "so dragging a slider while creating or editing a preset is audible "
        "immediately. The Downloads tab's Download History context menu gained a "
        "Remove All action that clears every completed and failed entry at once "
        "after confirmation, without deleting the downloaded files or touching "
        "active downloads."
    )),
    ("Version 1.1.75", (
        "Disabled playback rate controls on the Radio tab, including its context menu "
        "and rate shortcuts. Reverb preset changes now update the active BASS effect "
        "without toggling it off and on. The status bar shows station-reported codec "
        "and bitrate while detecting the stream format, retains those details if "
        "detection fails, and includes every field when read by a screen reader."
    )),
    ("Version 1.1.74", (
        "Migrated radio, podcasts, audiobooks, downloads, and local audio to an "
        "isolated BASS playback process. This replaces the previous audio engine for "
        "normal playback, improves buffering resilience, and prevents native decoder "
        "failures from terminating the main interface. Video pictures continue to use "
        "ffplay because BASS is audio-only.\n\n"
        "Connected BASS volume, pan, seeking, duration, completion, playback rate, pitch, "
        "ReplayGain, equalization, compression, echo, reverb, chorus, distortion, flanger, "
        "and gargle controls. Live radio remains non-seekable while podcasts, audiobooks, "
        "downloads, and local media use the seekable BASS path.\n\n"
        "RadioMaster+ is now licensed under GPL-2.0-or-later. The adapted FreeRadio BASS "
        "host retains attribution, and bundled Un4seen BASS binaries retain their separate "
        "free non-commercial-use terms."
    )),
    ("Version 1.1.73", (
        "Restored the proven v1.1.70 live-stream output-device and buffering policy, "
        "fixing recurring radio and YouTube audio breakups introduced in v1.1.72 while "
        "retaining the native PortAudio shutdown and crash protection.\n\n"
        "Implemented the parked accessibility options as working enhancements: concise "
        "screen-reader status announcements, F6 and Shift+F6 navigation between major "
        "regions, high-contrast focus highlighting, and a reduced-motion startup option.\n\n"
        "The shared content pane now shows readable podcast episode notes and YouTube "
        "video information, including descriptions and available metadata. Podcast RSS "
        "content:encoded notes are retained for newly imported episodes.\n\n"
        "Improved launch time by avoiding a duplicate station-catalog rebuild, and made "
        "Advanced settings apply YouTube-library auto-update changes immediately."
    )),
    ("Version 1.1.72", (
        "Stabilized radio and YouTube audio on bursty network streams with a larger "
        "decode-ahead queue, a two-second startup cushion, and a four-second recovery "
        "cushion after a real underrun. Audio underruns and output-device status faults "
        "are now recorded safely outside the real-time callback.\n\n"
        "Fixed a lyrics-request storm that could start duplicate network workers every "
        "time playback recovered from buffering. Stale results are now ignored when a "
        "track changes or stops.\n\n"
        "Fixed a confirmed native heap-corruption crash in audio shutdown by serializing "
        "PortAudio stream creation and destruction, preventing double-close races and "
        "overlapping callbacks. System Default now prefers Windows shared WASAPI instead "
        "of the legacy MME output path when available.\n\n"
        "Simplified Accessibility settings to functional visual preferences: high contrast "
        "and OpenDyslexic. Screen-reader support, full keyboard navigation, and native focus "
        "indicators remain always enabled throughout the application."
    )),
    ("Version 1.1.71", (
        "Completed the Podcasts, Downloads, Recordings, and Network settings wiring. "
        "Saved choices now reach their live services, dependent controls accurately follow "
        "their parent options, and controls have clear accessible names and behavior.\n\n"
        "Recording can preserve the source stream's actual format and bitrate, split tracks, "
        "and optionally discard likely advertisement segments at or below a configurable "
        "duration. Manual recordings now appear in Downloads, finalize cleanly during shutdown, "
        "and refresh completed tracks without waiting for a later poll.\n\n"
        "Proxy, timeout, and custom User-Agent settings now apply consistently to station and "
        "podcast APIs, playback, metadata, YouTube, downloads, updates, stream probing, and "
        "FFmpeg recording. Proxy URLs are normalized safely, and a blank User-Agent uses the "
        "current application version. Recording and wxPython shutdown tests are now isolated "
        "from background stream connections and late event-loop callbacks."
    )),
    ("Version 1.1.70", (
        "Completed the Playback settings wiring. Output device, crossfade, gapless playback, "
        "ReplayGain, normalization, position memory, and AcoustID configuration now have "
        "explicit defaults and connected runtime behavior. Playlist crossfades now begin "
        "before the outgoing track ends, gapless playback takes precedence when selected, "
        "and the AcoustID key link is actionable and accessible.\n\n"
        "Completed the Radio settings wiring. Country and duplicate filtering, automatic "
        "reconnection, reconnect limits, last-station playback, scheduled station updates, "
        "and manual updates are connected to their live consumers. Reconnect detail controls "
        "now follow the main toggle, invalid saved selections recover safely, and unexpected "
        "manual-update errors no longer leave the Update Now button disabled."
    )),
    ("Version 1.1.69", (
        "Removed the redundant, unlabeled Default Volume slider from Settings > Playback; "
        "the accessible transport-bar volume control remains the single persistent volume "
        "setting.\n\n"
        "Completed the General settings wiring. Language restart behavior is now explicit, "
        "themes list only real built-in and custom choices and apply immediately, Font Size "
        "and the combo boxes have accessible names, the tray-notification option is accurately "
        "described, and Apply now takes effect without closing the dialog.\n\n"
        "Fixed configuration instances sharing nested defaults and automatically migrated "
        "legacy language names such as English to ISO codes such as en."
    )),
    ("Version 1.1.68", (
        "Improved video-backend test isolation by making simulated ffplay processes "
        "match the real process interface and preventing unrelated Windows audio-session "
        "work during process-exit and stream-rejection tests. This removes background "
        "thread warnings and strengthens release verification without changing playback "
        "behavior."
    )),
    ("Version 1.1.67", (
        "Improved radio and YouTube audio stability on connections with packet-arrival "
        "jitter. Live playback now builds a decode-ahead cushion before starting and "
        "rebuilds it after an underrun instead of repeatedly alternating short audio "
        "fragments with silence.\n\n"
        "The transport state now reports buffering while that cushion is restored. "
        "Streams whose servers terminate the connection prematurely may still require "
        "automatic reconnection or selecting another source."
    )),
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
    """Topic tree + read-only content pane.

    The topic list is a wx.TreeCtrl: categories (Getting Started, Tabs
    and Panels, ...) as expandable branches with the individual topics
    as their children -- a flat list made every topic sit at the same
    level with no structure to navigate by, which for a screen-reader
    user meant arrowing through 30+ unrelated titles to find one
    section. The tree keeps the same keyboard model (arrows walk it,
    Enter expands/collapses a branch or opens a topic) and adds
    Left/Right to collapse/expand, with the accessible name unchanged.
    """

    def __init__(self, parent: wx.Window, *, title: str = "RadioMaster+ User Manual",
                 topics: list[tuple[str, str]] | None = None, config=None) -> None:
        super().__init__(parent, title=title,
                          size=(780, 520), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        source_topics = topics if topics is not None else USER_MANUAL_TOPICS
        active_config = config if config is not None else getattr(parent, "_config", None)
        self._topics = render_help_topics(source_topics, active_config)

        topics_label = wx.StaticText(self, label="&Topics:")
        # TR_HIDE_ROOT + a single invisible root item: the categories
        # appear as top-level branches without an artificial "All" node
        # above them. TR_TWIST_BUTTONS adds the +/- glyphs sighted users
        # expect; keyboard users expand with Right/Enter.
        self.topic_tree = wx.TreeCtrl(
            self, style=wx.TR_HIDE_ROOT | wx.TR_TWIST_BUTTONS
            | wx.TR_LINES_AT_ROOT | wx.TR_SINGLE,
        )
        set_accessible_name(self.topic_tree, "Help Topics")
        self._build_tree()

        content_label = wx.StaticText(self, label="Content:")
        self.content = wx.TextCtrl(
            self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_BESTWRAP,
        )
        set_accessible_name(self.content, "Help Content")

        close_btn = wx.Button(self, wx.ID_OK, label="&Close")

        left = wx.BoxSizer(wx.VERTICAL)
        left.Add(topics_label, 0, wx.BOTTOM, 4)
        left.Add(self.topic_tree, 1, wx.EXPAND)

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

        self.topic_tree.Bind(wx.EVT_TREE_SEL_CHANGED, self._on_topic_selected)
        close_btn.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_OK))

        # Select the first topic so the content pane starts populated,
        # exactly like the old list did with its SetSelection(0) --
        # walking down from the root finds the first topic-bearing item
        # in either tree shape (categorized or flat fallback).
        item = self.topic_tree.GetFirstChild(self._root)[0]
        while item.IsOk() and self.topic_tree.GetItemData(item) is None:
            item = self.topic_tree.GetFirstChild(item)[0]
        if item.IsOk():
            self.topic_tree.SelectItem(item)
        # A plain SetFocus() here gets overridden once ShowModal() gives the
        # default (Close) button initial focus -- EVT_INIT_DIALOG fires
        # after that, so setting focus there sticks.
        self.Bind(wx.EVT_INIT_DIALOG, self._on_init_dialog)

    def _build_tree(self) -> None:
        """Group the flat topic list into category branches. Topics are
        stored in tree item data as their index into self._topics, so
        selection maps straight back to the content.

        When every topic maps to the same category (Quick Start's five
        topics, Release Notes' version entries -- neither has a
        meaningful grouping), the category layer is skipped and topics
        sit at the top level, exactly like the old flat list."""
        self._root = self.topic_tree.AddRoot("Topics")
        categories_used = {
            _TOPIC_CATEGORIES.get(topic_title, "General")
            for topic_title, _body in self._topics
        }
        if len(categories_used) <= 1:
            for index, (topic_title, _body) in enumerate(self._topics):
                self.topic_tree.AppendItem(self._root, topic_title, data=index)
            return
        # category name -> tree item, created lazily in _CATEGORY_ORDER
        # so the tree shows the intended order, not insertion order.
        category_items: dict[str, wx.TreeItemId] = {}
        for category in _CATEGORY_ORDER:
            if category in categories_used:
                category_items[category] = self.topic_tree.AppendItem(
                    self._root, category,
                )
        for index, (topic_title, _body) in enumerate(self._topics):
            category = _TOPIC_CATEGORIES.get(topic_title, "General")
            item = category_items.get(category)
            if item is None:
                # A category not in _CATEGORY_ORDER (shouldn't happen,
                # but a new topic must never silently vanish).
                item = self.topic_tree.AppendItem(self._root, category)
                category_items[category] = item
            self.topic_tree.AppendItem(item, topic_title, data=index)
        # Expand everything: the whole point is seeing the structure,
        # and collapsed branches hide topics from arrow-key navigation
        # until expanded (a screen-reader user shouldn't have to guess
        # a branch needs opening).
        for category_item in category_items.values():
            self.topic_tree.Expand(category_item)

    def _on_init_dialog(self, event: wx.InitDialogEvent) -> None:
        event.Skip()
        self.topic_tree.SetFocus()

    def _on_topic_selected(self, event: wx.TreeEvent) -> None:
        # The tree fires SEL_CHANGED during Destroy() teardown (the
        # selection is cleared) -- by then the C++ peer is gone and any
        # query on it raises. Skip events once the tree is dead.
        if not self.topic_tree:
            event.Skip()
            return
        item = event.GetItem()
        if not item.IsOk():
            return
        data = self.topic_tree.GetItemData(item)
        if data is not None:
            self._show_topic(data)
        else:
            category = self.topic_tree.GetItemText(item)
            titles = []
            child, cookie = self.topic_tree.GetFirstChild(item)
            while child.IsOk():
                titles.append(self.topic_tree.GetItemText(child))
                child, cookie = self.topic_tree.GetNextChild(item, cookie)
            self.content.ChangeValue(
                f"{category}\n\nTopics in this category:\n\n"
                + "\n".join(titles)
                + "\n\nUse Right to expand this category, then select a topic to read it."
            )

    def _show_topic(self, index: int) -> None:
        if 0 <= index < len(self._topics):
            title, body = self._topics[index]
            self.content.ChangeValue(f"{title}\n\n{body}")
