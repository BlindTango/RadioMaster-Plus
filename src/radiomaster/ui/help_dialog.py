"""Help > Documentation dialog (F1) -- a topic list plus a read-only
content pane, with step-by-step instructions for every major feature and
the app's hardware requirements.
"""

from __future__ import annotations

import wx

from radiomaster.utils.accessibility import set_accessible_name

TOPICS: list[tuple[str, str]] = [
    ("Getting Started", (
        "RadioMaster+ streams internet radio, podcasts, YouTube videos, audiobooks "
        "(including DAISY), and local media files -- all fully operable by keyboard "
        "and screen reader.\n\n"
        "The main window has seven tabs, reached with Ctrl+1 through Ctrl+7 or by "
        "clicking a tab: Radio, Podcasts, Audiobooks, Media Player, YouTube, Downloads, "
        "and Scheduler. Below the tabs is the transport bar (Play/Pause, Stop, "
        "Next/Previous/First/Last, Volume, Rate, Pan, Record, Mute), which stays the "
        "same across every tab.\n\n"
        "On first launch, RadioMaster+ downloads the Radio Browser station catalog "
        "into a local database (a few seconds, shown in the status bar). After that, "
        "browsing is instant and works offline using the cached copy."
    )),
    ("Step by Step: Play Your First Station", (
        "1. Make sure the Radio tab is selected (Ctrl+1).\n"
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
        "1. Switch to the Podcasts tab (Ctrl+2).\n"
        "2. Use the search box to find a show, or File > Podcasts > Add Feed... to "
        "subscribe directly by RSS URL.\n"
        "3. Select an episode and press Play, or Download Episode to save it for "
        "offline listening (visible afterward in the Downloads tab).\n"
        "4. File > Podcasts > Import/Export OPML moves your whole subscription list "
        "to or from another podcast app."
    )),
    ("Step by Step: Download a YouTube Video", (
        "1. Switch to the YouTube tab (Ctrl+5).\n"
        "2. Search for a video or paste a URL.\n"
        "3. Select a result, choose a quality/format, and press Download Video "
        "(or Download Audio Only for MP3/Opus/FLAC extraction).\n"
        "4. Track progress in the Downloads tab (Ctrl+6) -- downloads are "
        "queue-based and can be paused/resumed."
    )),
    ("Step by Step: Read/Listen to an Audiobook", (
        "1. Switch to the Audiobooks tab (Ctrl+3) and browse to a DAISY 2.02 or "
        "NISO 39.86 book, or a ZIP archive containing one.\n"
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
        "The Downloads tab (Ctrl+6) shows every queued, in-progress, and completed "
        "download from Podcasts and YouTube in one place, with pause/resume and "
        "history. Download location, format, and metadata embedding are configured "
        "in Settings > Downloads."
    )),
    ("Global Hotkeys", (
        "Tools > Global Hotkeys... assigns system-wide key combinations to Play/"
        "Pause, Stop, Next/Previous Track, Volume Up/Down, Mute, Record, Open "
        "Settings, Open Recording Scheduler, and Open Help -- these work even when "
        "RadioMaster+ isn't the focused window, unlike the in-app keyboard shortcuts "
        "below.\n\n"
        "Press Add..., choose a feature, then the key combination you want (e.g. "
        "Ctrl+Alt+P). A feature can have more than one binding -- select an "
        "existing one and press Edit... or Remove to change it."
    )),
    ("In-App Keyboard Shortcuts", (
        "Tools > Keyboard Shortcuts... (Ctrl+K) lets you view and rebind every "
        "in-app action -- these only work while RadioMaster+ has focus, unlike "
        "Global Hotkeys above. Conflicts with an existing binding are flagged "
        "before you can save."
    )),
    ("Settings", (
        "Tools > Settings... (Ctrl+,) covers 9 categories: General, Playback, "
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
        "the Effects menu's Preset Manager and the Global Hotkeys editor, is "
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


class HelpDialog(wx.Dialog):
    def __init__(self, parent: wx.Window) -> None:
        super().__init__(parent, title="RadioMaster+ Help",
                          size=(780, 520), style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        topics_label = wx.StaticText(self, label="&Topics:")
        self.topic_list = wx.ListBox(self, choices=[t for t, _ in TOPICS])
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
        if 0 <= index < len(TOPICS):
            title, body = TOPICS[index]
            self.content.ChangeValue(f"{title}\n{'=' * len(title)}\n\n{body}")
