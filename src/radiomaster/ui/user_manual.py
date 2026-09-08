"""Complete in-app manual, organized by user task and application area.

Keep topic text and its category together so new topics cannot silently fall
into an unrelated category. Shortcut values are resolved by help_dialog.
"""

from textwrap import dedent

from radiomaster.ui.effects_data import BUILTIN_PRESETS, EFFECT_IDS, EFFECT_LABELS, PARAM_DEFS


def _topic(title: str, body: str) -> tuple[str, str]:
    return title, dedent(body).strip()


MANUAL_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    ("Getting Started", [
        _topic("Welcome and Overview", """
            RadioMaster+ brings internet radio, podcasts, local audio and video,
            audiobooks, YouTube, downloads, and scheduled recordings into one Windows
            application. This manual describes the controls available in this version,
            including features whose current implementation has limits.

            Start with Main Window and Menus, then open the category for the task you
            want to perform. Each main panel has an overview followed by detailed topics.
            Settings topics explain the controls in each settings category. The Keyboard
            Shortcut Reference shows your current assignments, including unassigned actions.

            Online radio, directory searches, YouTube, lyrics lookups, and updates need
            an internet connection. Local files and previously downloaded media can be
            played offline. A cached station catalogue can be browsed offline, but its
            online streams still need a connection.
        """),
        _topic("Using This Manual", """
            Open Help > User Manual, or use {shortcut:user_manual}. The manual is
            included with the application and can be read without internet access.

            1. In Help Topics, use Up and Down to select a category or topic.
            2. Use Right to expand a category and Left to collapse it or return to
               its parent. Select a topic to display its text.
            3. Press Tab to reach Help Content. Read with the arrow keys or your
               screen reader's text-reading commands. You can select and copy text.
            4. Use Shift+Tab to return to the topics. Choose Close to return to the app.

            Categories group related topics; they are not playback commands. Help >
            Quick Start Guide contains short introductory tasks, while Help > Release
            Notes describes changes by version. Shortcut values in this manual are
            refreshed when you reopen it after changing your assignments.
        """),
        _topic("Installation and First Launch", """
            Run the Windows installer and choose a standard installation or Portable.
            Portable installation lets you choose a folder without creating the normal
            shortcuts and file associations. Keep the executable and its accompanying
            folders together; copying only the executable is not sufficient.

            On first launch, allow the station catalogue to download. The status area
            reports loading and connection activity. If stations are missing, connect
            to the internet and use Settings > Radio > Update Now.

            Open Tools > Settings to choose your output device, storage folders, theme,
            and accessibility options. Choose Apply to save without closing, or OK to
            save and close. See Portable Mode and Backups before moving an existing copy.
        """),
        _topic("Main Window and Menus", """
            The main window contains the menu bar, global search, seven panels, the
            shared playback controls, the optional content display, and the status bar.
            The panels are Radio, Podcasts, Audiobooks, Media Player, YouTube, Downloads,
            and Scheduler. Changing panels does not by itself start new playback.

            File: Open File, Open URL, Open Folder, Import OPML, Export OPML, and Exit.
            View: Toggle Equalizer, Toggle Lyrics Panel, Fullscreen, Theme choices and
            Theme Editor, and Language.
            Effects: On/Off, built-in presets, and a preset manager for each effect.
            Tools: Sleep Timer, Download Manager, Recording Scheduler, Track Identifier,
            Split Track, Keyboard Shortcuts, Station Health Check, and Settings.
            Help: User Manual, Quick Start Guide, Release Notes, Update YouTube Library,
            Check for Updates, and About RadioMaster+.

            Download Manager opens the Downloads panel; Recording Scheduler opens the
            Scheduler panel. The playback controls act on current playback, although
            recording and item-navigation commands also depend on the selected panel.
        """),
        _topic("Your First Listening Session", """
            1. Open the Radio panel with {shortcut:panel_radio}.
            2. Enter a station name in that panel's Search field and press Enter.
            3. Select a result and press Enter or double-click to start it.
            4. Read Station/Media, Track/Show, and the status bar for playback details.
            5. Adjust Volume. Use Play/Pause to pause or resume, and Stop to stop listening.

            For offline media, choose File > Open File ({shortcut:open_file}) and select
            a supported file. For a playlist of local files, use File > Open Folder
            ({shortcut:open_folder}), then activate an item in the Media Player playlist.
        """),
    ]),
    ("Navigation and Playback", [
        _topic("Keyboard Navigation and Panel Switching", """
            Tab moves forward through available controls; Shift+Tab moves backward.
            Use arrows within lists, trees, choices, and sliders. Enter activates the
            selected station, episode, chapter, or media result. Space operates focused
            buttons and checkboxes. Disabled controls are skipped in normal tab order.

            Use Alt to reach the menu bar. On a supported list, Shift+F10 or the Context
            Menu key opens the same menu as a right-click. Escape closes most dialogs.

            Next panel: {shortcut:next_tab}. Previous panel: {shortcut:previous_tab}.
            Direct panel shortcuts: {panel_shortcuts}.

            With the region-navigation accessibility option enabled, F6 and Shift+F6
            move between major regions, including search, the selected panel, playback
            controls, and the visible content display. These supplement normal Tab navigation.
        """),
        _topic("Global Search and Panel Searches", """
            The top search bar has Global Search, Search Scope, and Go. Focus it with
            {shortcut:search}, enter text, choose a scope, then press Enter or Go. The
            search field's clear button clears its text.

            The scope list contains All, Radio, Podcasts, YouTube, Media, and Audiobooks.
            In this version, the global handler searches stored radio and media records;
            the other listed scopes are not connected to directory searches. All does
            not provide a combined search of all seven panels.

            Use the Radio panel's own Search for the station catalogue, the Podcasts
            Search for podcast directories, and YouTube Search with Videos, Channels,
            or Playlists. Browse audiobook files and folders from the Audiobooks panel.
        """),
        _topic("Play, Pause, Stop, and Position", """
            Play/Pause ({shortcut:play_pause}) changes between playing and paused.
            Activate a list item with Enter to choose what to play. Stop
            ({shortcut:stop}) ends playback; it is unavailable when nothing is active.

            The position slider seeks within media that has a known duration. The
            transport Rewind and Fast Forward buttons move 30 seconds. The seek
            shortcuts move 10 seconds: {shortcut:seek_backward} and {shortcut:seek_forward}.
            Elapsed, total, and remaining times are shown for finite media.

            Live radio has no fixed timeline: seek controls are disabled and only
            elapsed time is meaningful. Pause is not a guaranteed time-shift recording
            of everything broadcast while paused. Stop listening does not stop an
            independent radio recording; use Record or Downloads > Stop Recording.
        """),
        _topic("Volume, Mute, Rate, and Pan", """
            Volume changes listening level. The volume shortcuts change it in steps:
            {shortcut:volume_up} and {shortcut:volume_down}. Mute ({shortcut:mute}) toggles
            between Mute On and Mute Off. Windows also has application and device volume
            controls; check those if the player appears active but cannot be heard.

            Rate ranges from 0.5x to 3.0x for supported playback. The Rate slider and
            rate shortcuts are disabled on the Radio panel. On other panels, use the
            slider or {shortcut:rate_up} and {shortcut:rate_down}. The separate Speed Up
            and Speed Down shortcut actions adjust the same rate value when assigned.

            Pan balances sound left or right. Use the slider, {shortcut:pan_left}, or
            {shortcut:pan_right}. The radio context menu also offers Pan > Center.
            Volume, rate, and pan are remembered between sessions. Recording quality
            and output format are configured separately in Settings > Recordings.
        """),
        _topic("First, Previous, Next, and Last", """
            These commands depend on the selected panel. Their shortcuts are
            {shortcut:first_track}, {shortcut:previous_track}, {shortcut:next_track},
            and {shortcut:last_track}.

            Radio: move through stations played in this session. First and Last jump
            to the ends of that history; Previous and Next move one history entry.
            Podcasts: move through the loaded podcast's episodes in the chosen order.
            Downloads: move through playable items in Download History.

            On the other panels, these shared commands currently fall back to seeking:
            First seeks to the start, Last near the end, and Previous/Next move backward
            or forward. They are not audiobook chapter or YouTube playlist navigation.
            Select and activate the required chapter or result directly. Local media
            playlists can advance automatically when a track finishes.
        """),
        _topic("Now Playing and the Status Bar", """
            Station/Media identifies the station or media item. Track/Show contains
            supplied track information. Radio song names depend on metadata from the
            station, so a station can play normally without announcing each song.

            The status bar contains the main status, buffering progress, playback time,
            source, and stream format. A format might read AAC, 44.1 kHz, Stereo,
            192 kbps: codec, sample rate, channel arrangement, and bitrate.

            Station-reported codec and bitrate appear while the stream is checked and
            are labelled as station reported. Detected values replace them when available.
            Unknown fields are omitted; a failed check retains the reported fallback or
            says Stream format unavailable. The status bar's screen-reader name includes
            its populated fields. Automatic status announcements are optional in Settings.
        """),
        _topic("Opening Files, Folders, and URLs", """
            File > Open File ({shortcut:open_file}) opens a local media file. File >
            Open URL ({shortcut:open_url}) accepts a media or stream address. For YouTube
            page links, use YouTube > Play URL so the application resolves the media.

            File > Open Folder ({shortcut:open_folder}) fills the Media Player playlist
            with supported files from the folder and its subfolders. It replaces the
            current playlist; select an item and press Enter to play it.

            A website address is not necessarily a playable stream. If a URL opens a
            station website instead of audio, obtain the station's direct stream URL.
            Use Add RSS Feed for podcast feed addresses and Add Custom Station for a
            radio entry you want to keep in the catalogue.
        """),
    ]),
    ("Internet Radio", [
        _topic("Radio Tab", """
            Open Radio with {shortcut:panel_radio}. Its controls include Search, a
            station browsing section, groups and results, Add Custom Station, and
            station/now-playing information. Select a station and press Enter or
            double-click to listen. Radio playback continues when you visit another panel.

            Use the station context menu for Play/Pause/Resume, Stop, Favorites,
            Record/Stop Recording, Volume, and Pan. The Rate submenu is disabled.
            For recording instructions, open the Recording and Scheduling category.
        """),
        _topic("Browsing and Searching Stations", """
            Choose a browsing section such as Alphabetical, By Genre, By Country,
            By Language, By Network, Custom Stations, or Favorites. Choose a group
            where applicable, then move to the station results. All Stations and the
            corresponding All groups broaden the selection.

            In the Radio Search field, enter a station name, genre, country, or language
            and press Enter or Search. Results come from the local catalogue, including
            matches beyond the first part of the station list. The columns include the
            station name, country, and reported bitrate. These catalogue values can be
            stale; the status bar checks the actual stream separately.

            In station and group lists, type the beginning of a name to jump to a
            matching entry. This type-ahead navigation moves selection; it is separate
            from the Search field, which changes the results.

            Settings > Radio controls Default Country and Show duplicate stations.
            When duplicates are hidden, matching names are collapsed to a preferred
            entry; enable duplicates to inspect alternative streams for the same name.
        """),
        _topic("Favorites and Custom Stations", """
            To save a favorite, select the station, open its context menu, and choose
            Add to Favorites. Choose the Favorites section to find it again. Remove
            from Favorites removes that favorite designation, not the station catalogue.

            To add a stream absent from the catalogue, choose Add Custom Station,
            enter its name and stream URL when prompted, and confirm. Find it under
            Custom Stations. Use a direct playable URL rather than the station's homepage.

            Favorites and custom stations are stored locally. Back up the application's
            data when moving to a different installation; updating the public catalogue
            is not a substitute for backing up your personal entries.
        """),
        _topic("Station History and Reconnection", """
            Playing stations builds session history. Use the transport First, Previous,
            Next, and Last controls to revisit entries. History controls are unavailable
            at an end where there is nowhere further to go. This session history is
            separate from saved Favorites.

            Settings > Radio > Auto-reconnect on stream loss controls recovery attempts.
            Set the number of attempts and the interval between them. Turning automatic
            reconnection off disables its dependent settings. Automatically play the
            last station on launch resumes the last station connection on a future start.

            A failed stream can report a connection, format, or access problem. Try a
            different station to distinguish one unavailable stream from a network or
            output-device problem. A site may restrict access by region or reject clients.
        """),
        _topic("Refreshing the Station Catalogue", """
            Open Tools > Settings > Radio. Station list update frequency controls
            automatic catalogue refreshes. Update Now requests a refresh immediately;
            wait for its progress or completion message before judging the results.

            Refreshing downloads catalogue information. It does not prove that every
            stream works from your connection. Use Tools > Station Health Check to
            check availability and reported details. Hidden-station choices are managed
            in that tool rather than by changing the update frequency.
        """),
    ]),
    ("Station Health", [
        _topic("Station Health Check", """
            Tools > Station Health Check scans catalogue entries for dead streams,
            name mismatches, unavailable websites, geographic restrictions, and format
            mismatches. It is a diagnostic tool; a failure can be temporary or specific
            to your connection.

            1. Set Parallel connections to control how many stations are checked at once.
            2. Leave Skip stations checked in the last 7 days enabled for a shorter
               repeat scan, or clear it to check recent entries again.
            3. Choose Start Scan. Read the progress and results while it works.
            4. Choose Stop Scan to stop the scan. Close only closes the dialog: a running
               scan continues and can be revisited by reopening Station Health Check.

            The scan avoids streams currently being played or recorded. Reducing
            parallel connections can help on a slow connection. Results are retained
            locally so you can return to review them.
        """),
        _topic("Reviewing Results and Hiding Stations", """
            Use Show to select All problems, Dead streams, Name mismatches, Website
            down, Geo-blocked, or Format mismatches. Select a row to read its details.
            Recheck Selected tests it again; Play lets you try the selected station.

            Hide Selected excludes that station from normal browsing. Hide All Dead
            acts on the dead-station results after confirmation. A failed website does
            not necessarily mean the audio stream is dead; inspect the problem type.

            Choose Manage Hidden to review excluded stations. Unhide Selected restores
            one entry; Unhide All restores all hidden entries. Hiding is reversible and
            does not remove a station from the public Radio Browser service.
        """),
    ]),
    ("Podcasts", [
        _topic("Podcasts Tab", """
            Open Podcasts with {shortcut:panel_podcasts}. The panel has a Search field
            and three lists: Category, Podcasts, and Episodes. Categories are Subscriptions,
            Custom Feeds, and Directory. Select a podcast to load its episodes, then
            activate an episode with Enter or a double-click to play.

            The episode context menu provides Play/Pause/Resume, Stop, Download, and
            Download All. Other panel controls include Subscribe, Unsubscribe, Download
            Episode, Add RSS Feed, Import gPodder Subscriptions, Import OPML, and Export OPML.
        """),
        _topic("Finding and Subscribing to Podcasts", """
            1. Enter a show name or subject in the Podcasts Search field and choose Search.
            2. Select a result to inspect its episodes.
            3. Choose Subscribe to keep the podcast in Subscriptions.
            4. Return to Subscriptions and select the show whenever you want its episodes.

            Directory search uses the available podcast directories. Podcast Index can
            provide a second search directory when its API Key and API Secret are entered
            in Settings > Podcasts. They are separate from an AcoustID key.

            Select a subscription and choose Unsubscribe to remove it from your saved
            subscriptions. This is not a file-deletion command for downloaded audio.
        """),
        _topic("RSS Feeds, OPML, and gPodder Import", """
            Add RSS Feed accepts a podcast's RSS feed URL directly. Use it when a show
            is absent from search results; a podcast homepage is not always its RSS URL.
            Custom feeds can be found using the Custom Feeds category.

            Import OPML loads a file containing podcast feed addresses. Export OPML
            saves subscriptions to an OPML file for backup or another podcast player.
            Both are available in the Podcasts panel and the File menu. OPML does not
            contain downloaded audio, listening positions, or all application settings.

            To import public gPodder subscriptions, enter the gPodder Username in
            Settings > Podcasts, save it, then choose Import gPodder Subscriptions.
            This imports publicly available subscriptions. It is not authenticated
            two-way synchronization of private feeds or listening progress.
        """),
        _topic("Episode Playback, Resume, and Show Notes", """
            Select a show, select an episode, and press Enter. A downloaded local copy
            is used when available; otherwise playback uses the episode's online address.
            A saved position can produce a resume prompt. Choose whether to continue
            or begin again. Use the position slider for a specific point in finite audio.

            Settings > Podcasts > Episode order chooses Newest first or Oldest first.
            First/Previous/Next/Last follow the displayed order. Auto-advance to the next
            episode when one finishes continues through that show when enabled.

            Selecting an episode shows its description and available details in Content
            Display. If it is hidden, use View > Toggle Lyrics Panel. In Podcasts this
            shared display contains show notes rather than a song-lyrics lookup.
        """),
        _topic("Downloading Episodes and Complete Feeds", """
            Choose Download Episode or the episode context menu's Download to queue one
            episode. Download All queues episodes currently listed for that podcast after
            one confirmation. Already downloaded or queued episodes can be skipped.

            Downloads are placed in the Podcast Download Location configured in Settings
            > Podcasts, with a subfolder for the show. Audio format and quality follow
            download settings. Available show notes are saved alongside episode downloads.
            Use Downloads to inspect progress, failures, and completed files.

            Enable Auto-download new episodes in Settings > Podcasts for automatic
            downloads. Episodes to download per podcast accepts -1 for unlimited, 0
            for none, or a positive limit. Episodes to keep is a separate retention
            setting: it can remove older downloaded episode files and their history
            entries, not just hide rows. Choose both deliberately before enabling a
            large feed's downloads. Unlimited downloading does not disable retention.
        """),
    ]),
    ("Audiobooks", [
        _topic("Audiobooks Tab", """
            Open Audiobooks with {shortcut:panel_audiobooks}. Browse Folder loads a
            folder of audio files or a DAISY book; Browse File opens a single audiobook
            file. The panel shows Library, Title, Chapters, Read with TTS, Stop TTS,
            and Add Bookmark.

            1. Choose Browse Folder or Browse File and select your book.
            2. Select a chapter or file in Chapters.
            3. Press Enter or double-click to play it.
            4. Use the shared playback controls for pause, volume, rate, and seeking.

            A single file is listed as one item; do not assume its embedded chapters
            will become separate rows. Browse is the working way to reopen a book:
            the Library tree is not currently a complete saved-book navigation interface.
        """),
        _topic("DAISY Books and Chapter Playback", """
            Use Browse Folder to select the extracted DAISY book folder containing its
            navigation files and media. The parser supports DAISY 2 and DAISY 3 structures.
            A loaded-book message reports the format and discovered chapters/audio files.

            Select a chapter and activate it. Books without a usable chapter list can
            be listed by their audio files instead. Keep the book's folder structure
            intact so relative media references continue to work.

            Chapter navigation currently selects associated audio files. The application
            does not provide a complete DAISY player with page-number navigation or
            guaranteed synchronized sentence highlighting. Use chapter selection and
            the media position controls for the navigation available here.
        """),
        _topic("Audiobook Resume and Bookmarks", """
            The application stores a listening position for a loaded audiobook. Reopening
            the same book can offer Resume Playback. Accept to use the saved position
            when playback starts, or decline to start normally.

            Select a chapter and choose Add Bookmark to save its title, book location,
            and the current audio position. A message confirms the save. This version
            does not expose a bookmark list, jump-to-bookmark command, or bookmark editor.
            Saved bookmarks should therefore not be treated as a complete navigation tool.

            Resume is stored for the book rather than a full chapter-by-chapter reading
            history. When reopening a folder book, select the intended chapter before
            applying a saved position. Back up data and the book files together.
        """),
        _topic("Reading Book Text with TTS", """
            For a DAISY chapter containing text, select the chapter and choose Read with
            TTS. The application sends that text to Windows SAPI speech. If the chapter
            has no text, it reports No Text; audio-only files cannot be read as text.

            Choose the engine, installed voice, speech rate, and speech volume in
            Settings > Audiobooks. Windows SAPI 5 is currently supported. Preview Voice
            lets you listen before saving; Apply or OK saves your choices for the next
            Read with TTS. Stop TTS stops book speech.

            TTS is separate from recorded-audio playback. The shared transport rate,
            pause, and seeking controls do not operate speech. Audio-only books do not
            contain text to read and cannot be converted to text by this button.
        """),
    ]),
    ("Local Media", [
        _topic("Media Player Tab", """
            Open Media Player with {shortcut:panel_media}. Its File Browser Tree is on
            the left and Playlist on the right. Browse Folder changes the browser root.
            Select a media file and choose Add to Playlist; activate a playlist row to play.

            The playlist shows available title and artist tags, falling back to the
            filename when needed. Clear empties this playlist without deleting the source
            files. File > Open Folder loads supported files recursively into a replacement
            playlist, which is different from browsing a folder in the file tree.

            Supported file choices include common MP3, FLAC, OGG, WAV, AAC, M4A, WMA,
            Opus, and M4B audio, plus MP4, MKV, AVI, WebM, and MOV video. Whether a file
            plays also depends on its codec and whether it is damaged or protected.
        """),
        _topic("File Browser and ZIP Archives", """
            Browse Folder displays folders and supported media in File Browser Tree.
            Expand folders with the Right arrow and collapse with Left. Select an actual
            file and use Add to Playlist. Open File lets you choose a file directly
            and adds it to the playlist; activate its row to play.

            Open Archive displays the contents of a ZIP archive in the tree. Archive
            browsing currently does not extract member files for playback. Extract the
            archive with your archive tool, then browse the extracted folder to play it.

            The file chooser also lists M3U and PLS playlist extensions. There is no
            playlist import/export editor in this panel; individual entries and folder
            loading are the supported ways to build its visible playlist.
        """),
        _topic("Automatic Advance, Crossfade, and Gapless", """
            When an item started from the local playlist finishes, the next item can
            start automatically. The end of the list stops this progression. Clearing
            the playlist also clears the list used for automatic advancement.

            Settings > Playback has Crossfade Duration and Gapless playback. Crossfade
            requests a transition between outgoing and incoming items. Gapless takes
            precedence when both are selected and advances at the natural end instead.

            Transition support depends on the playback path. The current BASS path
            switches streams rather than guaranteeing a true overlapping crossfade.
            These settings should not be interpreted as a guarantee of uninterrupted
            audio across every codec or device. They do not create a YouTube playlist queue.
        """),
        _topic("Video Playback and Fullscreen", """
            Open a local video or activate a YouTube video to use video playback. Video
            can appear in its own playback window while RadioMaster+ remains the place
            to select media and manage downloads.

            View > Fullscreen ({shortcut:toggle_fullscreen}) changes the main RadioMaster+
            window's fullscreen state. It is separate from the external video's own window.
            Audio-only YouTube selection avoids opening video playback.

            Some audio-setting changes use a different playback path for video and can
            take a restart of that playback to become audible. Keep this distinction in
            mind when comparing effects on radio, local audio, and video.
        """),
    ]),
    ("YouTube", [
        _topic("YouTube Tab", """
            Open YouTube with {shortcut:panel_youtube}. Enter text, choose Type (Videos,
            Channels, or Playlists), and choose Search. Select a result and press Enter
            or double-click. A video plays; a channel opens its videos; a playlist opens
            its entries. The results columns change to fit the selected search type.

            The panel also has My Channels, Subscribe to Channel, Unsubscribe, Play URL,
            Load Playlist, Download, Download Audio, Quality, and Audio Format. Selecting
            a video shows its available description and details in Content Display.
        """),
        _topic("Playing Videos and Direct Links", """
            To play a search result, select a video and activate it. To use a link,
            choose Play URL and paste the YouTube address. Wait while the player resolves
            the stream; some videos require preparation before playback starts.

            Quality offers best, 1080p, 720p, 480p, 360p, and audio only. Availability
            depends on the video. Select audio only for listening without video. The
            application may prepare a temporary local file when direct playback fails.

            If a video is unavailable or playback is rejected, read the error, update
            the YouTube library from Help, and try again. Private, removed, restricted,
            or otherwise inaccessible videos are not guaranteed to play.
        """),
        _topic("Channels and Playlists", """
            Search with Type set to Channels, then activate a result to list its videos.
            Subscribe to Channel saves a channel in My Channels. Activate a saved channel
            to load its videos; Unsubscribe removes the local saved entry.

            These are RadioMaster+ channel subscriptions, not changes to a signed-in
            YouTube account. The application does not provide a YouTube account manager.

            Search for Playlists and activate a result, or choose Load Playlist and
            enter its URL. Select individual entries to play or download. Loading a
            playlist displays its entries; it is not a promise of automatic sequential
            playback or a bulk-download command for the entire playlist.
        """),
        _topic("Downloading Video or Audio", """
            1. Select a video result or playlist entry.
            2. Choose the desired Quality for video, or Audio Format for extracted audio.
            3. Choose Download for the video workflow, or Download Audio for audio extraction.
            4. Open Downloads ({shortcut:download_manager}) to follow progress and play
               the completed file from Download History.

            Settings > Downloads supplies the destination, concurrency, audio quality,
            and metadata/artwork options. Audio formats are MP3, AAC, FLAC, M4A, Opus,
            and WAV. The Audio Format selector is updated when
            download settings are applied. A higher output bitrate cannot restore detail
            missing from the original media. A failed download can be retried from History.
        """),
    ]),
    ("Downloads and Saved Files", [
        _topic("Downloads Tab", """
            Open Downloads with {shortcut:panel_downloads} or Tools > Download Manager.
            Active Downloads shows queued or running work and active radio recordings.
            Download History contains completed and failed entries. Refresh reloads
            the lists; they also update during normal operation.

            Select a history item and choose Play, press Enter, or double-click to open
            a completed file. Files must still exist at their recorded locations.
            Recordings and podcast downloads can appear here as well as YouTube downloads.
        """),
        _topic("Progress, Restart, Retry, and Remove", """
            Read an active row's status and progress before taking action. Its context
            menu offers Restart for a normal download, or Stop Recording for a running
            recording. Restart resubmits a download. Failed History entries offer Retry.

            Remove on an active normal download removes its list/database entry; it
            does not cancel the background transfer. The confirmation explains this.
            Do not use Remove as a pause or cancellation control. A live recording
            must be stopped with Stop Recording so its output can be finalized.

            Remove in Download History deletes the history entry, not its saved file.
            Remove All clears completed/failed history after confirmation, including
            entries beyond the current display limit. It does not delete downloaded files
            or clear active work. Use Windows file management for actual file deletion.
        """),
        _topic("History Length and Playback Navigation", """
            Settings > Downloads > Download History entries to show controls the number
            of rows loaded into History. Enter -1 for unlimited or a positive number
            for that many recent entries (50 by default). Zero is treated as a minimum
            of one entry in this version. This is a display limit;
            it does not delete stored history or media.

            First/Previous/Next/Last on the Downloads panel navigate its available
            history items. First targets the beginning of the displayed history order
            and Last its end. Failed entries or files that have moved cannot be played.
            Increase the history limit if the item you want is older than those shown.
        """),
        _topic("Download Locations, Formats, and Quality", """
            Settings > Downloads > Download Location is the general destination.
            Podcasts have their own Podcast Download Location in Settings > Podcasts;
            recordings use Recording Location in Settings > Recordings.

            Max Concurrent Downloads limits simultaneous work. Audio Format and Audio
            Quality control extracted audio; the interface offers fixed bitrates and
            Best. Embed metadata and Embed artwork add supplied information when supported
            by the source and output format. Missing source artwork cannot be invented.

            Changing a destination affects new work; it does not move existing files.
            Keep enough free space for downloads and temporary preparation. For a portable
            setup, destinations inside the application folder travel with that copy;
            destinations on other drives remain external locations.
        """),
    ]),
    ("Recording and Scheduling", [
        _topic("Starting and Stopping a Radio Recording", """
            1. Open Radio and select the station to record.
            2. Choose Record in its context menu, use the transport Record button, or
               press {shortcut:record}.
            3. Check Recording On and the Active Downloads entry.
            4. Use Stop Recording on the selected station or in Downloads to finish.
            5. Find finalized output in Recording Location and Download History.

            Recording uses its own stream connection. You can listen to another station
            and can record more than one station. Stop playback and Mute affect listening,
            not these independent recordings. The radio Record indicator follows the
            selected station; use Downloads to review all active recordings.
        """),
        _topic("Recording Format, Quality, and Metadata", """
            Open Settings > Recordings before starting new recordings. Recording Location
            chooses the output folder. Record in the station's original format when possible
            attempts to preserve its codec, bitrate, sample rate, and channels.

            While source matching is enabled, Recording Format and Recording Quality
            are disabled. Turn it off to choose your own format and quality. Lossless
            formats do not use the same bitrate selector as lossy output. Best uses the
            available source information rather than a guarantee of improved quality.

            Add metadata to recordings writes available track information. The stream
            must supply usable information for reliable titles. Changes apply to newly
            started recordings. Audio effects and listening volume are not a recording
            mastering interface; the recording path captures the station separately.
        """),
        _topic("Splitting Recordings and Short Segments", """
            Split recordings into tracks uses station track metadata changes to finalize
            segments. When the station does not identify songs accurately, boundaries
            and filenames may also be inaccurate. Turn splitting off for a continuous
            recording, or split a saved recording later with Tools > Split Track.

            Skip likely advertisements based on short segment duration is a heuristic
            applied to split segments. Maximum likely advertisement duration sets the
            threshold in seconds. These dependent controls are available when splitting
            and short-segment skipping are enabled.

            Short music, announcements, or speech may also fall below the threshold.
            Turn skipping off when you need every segment. It is not content recognition
            and cannot reliably distinguish every advertisement from wanted audio.
        """),
        _topic("Scheduler Tab", """
            Open Scheduler with {shortcut:panel_scheduler} or Tools > Recording Scheduler
            ({shortcut:recording_scheduler}). Scheduled Recordings lists saved jobs.
            Add Schedule creates one; Edit changes the selected job; Delete removes it
            after confirmation. An enabled schedule is eligible to run at its start time.

            The scheduler runs inside RadioMaster+. Keep the application running and
            the computer awake with a working connection. Hiding the app in the tray is
            different from exiting. The scheduler is not a Windows wake-up service.
        """),
        _topic("Creating and Editing a Schedule", """
            1. Choose Add Schedule and enter Stream/Podcast URL and a descriptive Title.
            2. Choose Source Type: Radio Station, Podcast, Audiobook, or YouTube.
            3. Set Start Date and Start Time using the computer's local clock.
            4. Set Duration in minutes. Zero means until the source ends; a continuous
               radio stream may have no natural end, so use a finite duration if needed.
            5. Choose Recurrence: None, Daily, Weekly, Monthly, or Weekdays.
            6. Choose Recording Format: auto, mp3, aac, opus, wav, or flac.
            7. Leave Enabled checked to run the job, then save with OK.

            Edit uses the same fields. Clear Enabled to retain a job without running it.
            Auto uses recording defaults; the source-matching recording option can take
            precedence over a requested encoding. Source Type labels the job: the recording
            path still needs a directly playable source, not an arbitrary YouTube webpage
            or a podcast RSS feed. The scheduler does not resolve every page URL for you.
        """),
        _topic("Scheduled Recording Output and Overlaps", """
            Scheduled recordings use Recording Location and the same recording options
            for source matching, quality, track splitting, short segments, and metadata.
            A positive Duration stops the recording after that number of minutes.

            Review overlapping jobs and ensure the connection and disk can support them.
            Multiple stream connections may also be limited by a station. A disabled or
            deleted schedule prevents future scheduled runs; do not assume deleting its
            row is a control for stopping an already running recording.

            Check the status and output after an important job. Closing the application
            interrupts its scheduler; expired recording times are not a guarantee that
            missed broadcast audio can be recovered.
        """),
    ]),
    ("Audio Effects", [
        _topic("Using the Effects Menu", """
            Open Effects and choose an effect. On/Off toggles it, a named preset selects
            a ready-made setting, and the effect's Manager opens its preset controls.
            Selecting a preset also enables that effect. A checked preset name and the
            On/Off checkmark describe different parts of its state.

            Multiple effects can be enabled. Their state and parameters are saved for
            future sessions. Use On/Off for a quick comparison and moderate listening
            volume when making changes. These effects process listening audio, not the
            independent station recording connection.

            Audio backends differ. BASS applies reverb, echo, chorus, compressor,
            distortion, flanger, and gargle parameter updates live without toggling the
            effect off and on. Some controls are approximated or limited by the native
            effect: for example, Echo's In Gain and Gargle's Depth have no effect there.
            Equalizer settings map into broader bands. Dynamic Range currently shares
            the Compressor effect rather than applying its own complete parameter set.
            Video uses a separate path and can restart for changes.
        """),
        _topic("Creating and Managing Effect Presets", """
            Open Effects > the effect > its Manager. The list includes built-in and
            user-created presets. Select a preset and choose Apply to use it and close
            the manager. Built-in presets cannot be edited, renamed, or deleted.

            New opens parameter sliders seeded from the selection or current settings.
            Adjust them, confirm, and enter a new preset name. Edit changes a selected
            custom preset; Rename changes its name; Delete removes it after confirmation.
            Use a distinct name to avoid replacing an existing custom preset.

            Parameter sliders send live preview changes on supported playback paths.
            Canceling an edit does not guarantee that audible preview changes are undone.
            Reapply the previous preset or turn the effect off to return to known settings.
            Creating or saving a preset is separate from choosing Apply in the manager.
        """),
        _topic("Equalizer Window", """
            View > Toggle Equalizer ({shortcut:toggle_equalizer}) opens the equalizer
            controls. Adjust frequency-band sliders to change bass, midrange, and treble.
            The bands run from 32 Hz through 16 kHz. The effect also has its own presets
            under Effects > Equalizer.

            The equalizer window has Preset, Save as Preset, Delete Preset, an Enable
            Equalizer checkbox, and live band adjustments. Save as Preset creates a
            named choice in that open dialog; Delete Preset removes a custom choice.
            Those dialog-local custom choices are not stored persistently. Use the
            Effects > Equalizer manager for custom presets saved between sessions. Confirm
            the settings you want to keep. With the BASS backend, the ten UI bands are
            grouped into bass, vocal, and treble ranges rather than ten independent
            narrow filters, so adjacent sliders can have related results.
        """),
    ]),
    ("Additional Tools", [
        _topic("Lyrics and the Content Display", """
            View > Toggle Lyrics Panel ({shortcut:toggle_lyrics}) shows or hides Content
            Display. For radio and tagged local music, the player looks up lyrics using
            the artist and title. Supplied timed lyrics can highlight the current line;
            plain lyrics are displayed without timing.

            In Podcasts, the same display shows the selected episode's show notes. In
            YouTube, it shows available video details and description. These are not
            automatically replaced by song lyrics for those panels.

            The display is read-only, supports text selection/copying, and can be reached
            by keyboard. Missing metadata, an unavailable lyrics service, or a track
            without lyrics can leave it empty or show an explanatory message. It is not
            an automatic transcription or DAISY synchronized-reading service.
        """),
        _topic("Track Identifier", """
            Tools > Track Identifier ({shortcut:track_identifier}) attempts to identify
            the current track and reports available title, artist, album, and source.
            Start the media you want to identify before invoking the tool. If nothing
            is loaded, a file chooser lets you select an audio file to identify.

            Settings > Playback contains the AcoustID API Key field and a link for
            obtaining a key. Fingerprint-based identification needs that service and a
            working connection; available metadata may also assist identification.

            Identification can fail for unknown recordings, unsuitable sources, or
            missing service configuration. This command displays a result; it is not
            a general file-tag editor or a promise to identify every live broadcast.
        """),
        _topic("Track Splitter", """
            Tools > Split Track opens a tool for splitting a saved audio file.

            1. Browse for Source Audio File.
            2. Choose a separate Output Folder for the resulting segments.
            3. Select Silence Detection or Chapter Markers as Split Method.
            4. Enter a Filename Template using {prefix}, {index}, and {title} as needed.
            5. Choose Split and read the progress/results log.

            Silence Detection depends on pauses in the audio. Chapter Markers requires
            suitable chapter data in the file. Inspect the resulting segments because
            pauses do not always correspond to song or chapter boundaries. This tool
            works on a saved file and is separate from live recording's metadata splitting.
        """),
        _topic("Sleep Timer", """
            Open Tools > Sleep Timer ({shortcut:sleep_timer}). Set Duration in minutes
            from 1 to 480, choose a Mode, and select Start Timer. Reopen the dialog to
            inspect whether it is running and the remaining time shown there.

            Stop Timer cancels the timer; Close closes the dialog without canceling it.
            When the timer expires, it stops listening playback rather than shutting
            down Windows. Independent radio recordings are not controlled by this timer.

            Mode lists Countdown, End of Track, and End of Playlist. In this version,
            all three are wired to stop at the elapsed countdown. The latter two do
            not yet defer stopping until a track or playlist boundary. Use Countdown
            when choosing the behavior you can currently rely on.
        """),
    ]),
    ("Settings", [
        _topic("Settings", """
            Open Tools > Settings ({shortcut:settings}). Choose a category, then Tab
            through its controls. Categories are General, Playback, Radio, Podcasts,
            Audiobooks, Downloads, Recordings, Network, Accessibility, and Advanced.

            Apply saves the visited categories and keeps Settings open. OK saves and
            closes. Cancel closes without saving changes made since the last Apply;
            it does not reverse settings already applied. Language changes require a
            restart, and reduced-motion startup changes apply on the next launch.

            Some choices disable dependent controls: for example, proxy details when
            Use proxy server is off, and recording format when matching the source.
            Each category below describes its controls and related task topics.
        """),
        _topic("General Settings", """
            Language chooses an available interface language and applies after restart.
            Theme selects an available theme. Font Size changes interface text size.
            View > Theme offers Default Light, Default Dark, and Theme Editor as well.

            Start on boot requests launch when you sign in to Windows. Minimize to
            system tray hides the window when minimized. Close to system tray makes
            the window's close action hide it instead of exiting. Show system tray
            notification when RadioMaster+ is hidden controls the hiding notification.

            Use the tray menu's Show RadioMaster+ to restore the window, and its Exit
            command or File > Exit when you intend to terminate the application.
        """),
        _topic("Playback Settings", """
            Sound Output Device selects where listening audio is sent. If a device is
            disconnected, choose another available output and check Windows sound settings.

            Crossfade Duration sets the requested transition length. Gapless playback
            selects natural-end advancement instead of overlapping transitions. See
            Automatic Advance, Crossfade, and Gapless for backend limitations.

            ReplayGain offers None, Album, and Track and uses available gain tags.
            Normalize audio (EBU R128) requests loudness normalization; support depends
            on the playback path, and the current BASS effects mapping does not supply
            a full EBU R128 normalization stage. Remember playback position enables
            general media progress restoration where supported.

            AcoustID API Key is used by Track Identifier. Use the nearby key link to
            configure that feature; it is unrelated to podcast-directory credentials.
        """),
        _topic("Radio Settings", """
            Default Country selects a preferred country from the available list or All.
            Show duplicate stations controls whether repeated station names remain visible.

            Auto-reconnect on stream loss enables recovery. Reconnect attempts before
            giving up and Interval between reconnect attempts control its limits.
            Automatically play the last station on launch starts that station on a
            future application launch when enabled.

            Station list update frequency controls scheduled catalogue refreshes:
            Off (manual only), Daily, Weekly, Monthly, Quarterly, Every 6 months, or Yearly.
            Update Now performs a manual refresh and reports progress in Settings.
            Use Station Health Check separately to inspect broken or mismatched entries.
        """),
        _topic("Podcast Settings", """
            Podcast Download Location chooses the destination for podcast files.
            Auto-download new episodes enables automatic queueing. Episodes to download
            per podcast accepts -1 for unlimited, 0 for none, or a positive limit; this
            control is disabled while automatic downloading is off.

            Episodes to keep controls retention separately from the automatic-download
            limit and can delete older downloaded episode files and related history.
            Its range is 1 to 1000; it has no unlimited choice. Episode order chooses
            Newest first or Oldest first. Auto-advance to
            the next episode when one finishes controls continuation in the selected show.

            gPodder Username is for importing public subscriptions. Podcast Index API
            Key and API Secret enable the additional directory search. Save changes
            before using the related import or search commands.
        """),
        _topic("Audiobook Settings", """
            Open Tools > Settings and select Audiobooks in the category list.
            Choose your engine and voice, adjust speech rate and volume, and use
            Preview Voice to hear a sample. Select Apply or OK to save your choices.

            TTS Engine selects the speech engine used by Read with TTS. Windows SAPI 5
            is currently supported. Voice lists the compatible voices installed for
            this application, plus System default voice. Windows OneCore-only voices
            and voices installed solely for a different application architecture may
            not appear in this list. Some installed voices use online services and
            require a working connection to their provider.

            Speech Rate ranges from -10 to 10, with 0 as normal. Speech Volume ranges
            from 0 to 100. These are separate from the recorded-audio transport controls.
            Preview Voice uses your unsaved choices; Stop Preview stops the sample.
            Leaving this category or closing Settings also stops the preview.

            Apply or OK saves the engine, voice, rate, and volume for the next book
            reading. Cancel does not save a previewed choice. If a saved voice is no
            longer installed, select an available voice or System default voice. To
            use voices installed while the app was running, reopen Settings.

            On the Audiobooks panel, select a book and a chapter containing text,
            then choose Read with TTS. Stop TTS stops the reading. Changing settings
            applies when you next choose Read with TTS; it does not change speech
            already in progress. Recorded audiobook audio uses playback controls.
        """),
        _topic("Download Settings", """
            Download Location is the destination for general downloads. Max Concurrent
            Downloads controls how many transfers run at once. Audio Format and Audio
            Quality select extracted-audio output; quality choices include 96k, 128k,
            192k, 256k, 320k, and Best.

            Embed metadata and Embed artwork request supplied tags and images in
            supported output formats. These options do not edit all pre-existing files.

            Download History entries to show accepts -1 for unlimited or a positive
            count; zero is currently treated as one. The display limit is not automatic deletion. See History
            Length and Playback Navigation before clearing older history entries.
        """),
        _topic("Recording Settings", """
            Recording Location chooses the folder for new recordings. Record in the
            station's original format when possible takes priority over manual format
            and quality selections and disables those controls while enabled.

            Recording Format and Recording Quality apply when source matching is off.
            Formats are MP3, AAC, OGG, Opus, FLAC, and WAV. Quality choices are 128k,
            192k, 256k, 320k, and Best; FLAC and WAV do not use a bitrate setting.
            Split recordings into tracks separates segments using station metadata.
            Skip likely advertisements based on short segment duration and Maximum
            likely advertisement duration control optional short-segment removal.
            Add metadata to recordings writes supplied track information.

            See Recording Format, Quality, and Metadata and Splitting Recordings and
            Short Segments for the consequences of these choices. A recording already
            running is not reconfigured by changing settings for the next session.
        """),
        _topic("Network Settings", """
            Use proxy server enables Proxy Host and Proxy Port. Enter the proxy address
            and port supplied for your connection. Turning the option off disables its
            fields and uses the ordinary connection path.

            Connection Timeout is measured in seconds and controls how long supported
            network operations wait. Custom User Agent changes the client identification
            sent to supported HTTP services; leave it blank for the application default.

            Apply changes before retrying a failed operation. A proxy or a different
            user agent does not guarantee access to a station or video that restricts
            clients or geographic regions. The dialog has no proxy-authentication fields.
        """),
        _topic("Accessibility Settings", """
            Use black and white high contrast colors overrides the usual palette.
            Use OpenDyslexic font when installed requests that font; Windows falls back
            to its interface font if OpenDyslexic is not installed.

            Announce status changes to screen readers enables automatic announcements.
            The status bar remains readable when this is off. Use F6 and Shift+F6 to
            move between major regions enables those extra navigation keys. Enhance
            keyboard focus with high contrast highlighting adds a stronger focus cue.

            Reduce motion by skipping the startup splash affects the next launch.
            The other options apply with Apply or OK. Control names, normal keyboard
            navigation, and native focus indicators remain available independently.
        """),
        _topic("Advanced Settings", """
            Logging Level offers Off, Info, Debug, and Input/Output. Info is suitable
            for normal use; more detailed levels help investigate a problem but can
            create larger logs and affect performance. The category displays the log
            location for this installation.

            Automatically update the YouTube library (yt-dlp) in the background enables
            periodic library updates. Checks occur when enabled and on later startups,
            at most weekly. Help > Update YouTube Library performs a manual update.
            This library update is separate from updating RadioMaster+ itself.
        """),
    ]),
    ("Accessibility and Customization", [
        _topic("Accessibility Notes", """
            RadioMaster+ uses named Windows controls, keyboard navigation, and readable
            text panes for screen-reader use. The transport buttons have names such as
            Play, Stop, and Recording On instead of relying on their visual symbols.

            Use list navigation to read columns, Shift+F10 for list commands, and Tab
            to enter read-only content. Read the status bar for source and audio format
            details. Configure optional announcements and region navigation in Settings
            > Accessibility if they help your workflow.

            External video playback, Windows dialogs, and unavailable services can behave
            differently from the main interface. Read the specific feature's topic for
            limitations rather than assuming every visible placeholder is fully functional.
        """),
        _topic("Keyboard Shortcuts", """
            Open Tools > Keyboard Shortcuts ({shortcut:keyboard_shortcuts}). Filter
            features by typing in Filter features. Select a feature to inspect its
            assignment, category, and scope.

            New assigns an unassigned feature. Edit changes a selected assignment.
            Choose Feature, Main key, and the desired modifier checkboxes. Available
            modifiers distinguish left and right Shift, Ctrl, Alt, and Windows keys.
            The dialog reports assignment conflicts before accepting the combination.

            Global shortcut lets the command work when another application is focused,
            subject to Windows registering the key. Delete removes an assignment without
            removing its feature. Reset All to Defaults restores the catalogue after
            confirmation. Save the shortcut editor to apply changes; reopen this manual
            to see them in the reference and task instructions.
        """),
        _topic("Keyboard Shortcut Reference", """
            The following list is generated from the same feature catalogue and saved
            assignments used by the application. In app means RadioMaster+ must have
            focus. Global means the shortcut was configured for use outside the app;
            another application's key registration can prevent it from registering.
            Unassigned means the feature currently has no shortcut.

            {shortcut_reference}

            These commands supplement ordinary Tab, Shift+Tab, arrow keys, Enter,
            Space, and context-menu navigation. F6 region navigation is configured
            separately under Accessibility settings.
        """),
        _topic("Themes, Colors, and Font Size", """
            View > Theme provides Default Light and Default Dark. Settings > General
            also offers Theme and Font Size. High contrast and enhanced focus options
            are in Settings > Accessibility and can override normal theme colors.

            View > Theme > Theme Editor opens Theme Colors and Live Preview. Activate
            a color entry to choose its color. The entries cover primary/secondary/tertiary
            backgrounds, primary/secondary text, accent and accent hover, highlight and
            highlight text, success, warning, error, border, control face, and control text.
            Apply updates the current theme; Save
            Theme asks for a name and saves/applies a custom theme. Reset reloads the
            current theme's colors, not necessarily a factory theme.

            Load Theme accepts a JSON file, but the current load path can restore the
            active theme over the imported values. Confirm the preview before applying;
            external theme import should not be assumed to work reliably in this version.
            Use the built-in choices to return to a known palette.
        """),
        _topic("System Tray, Startup, and Exiting", """
            Enable Minimize to system tray or Close to system tray in General settings
            if you want playback to continue while the main window is hidden. The
            optional tray notification indicates that the app has been hidden.

            The tray menu has Show RadioMaster+, Play/Pause, Stop, and Exit. Show restores
            the main window; double-clicking the tray icon also restores it. Use Exit
            when you want the application to terminate rather than remain hidden.

            Start on boot is a separate General setting for launching at Windows sign-in.
            Automatically play the last station is in Radio settings. Enable both only
            if you want the application to launch and start that station at sign-in.
        """),
    ]),
    ("Updates, Storage, and Troubleshooting", [
        _topic("Checking for Updates", """
            Help > Check for Updates ({shortcut:check_updates}) checks for a newer
            RadioMaster+ release. Read the release notes before choosing Download &
            Install. View on GitHub opens the release page. Skip This Version dismisses
            that version for automatic prompting; Remind Me Later postpones the update.

            After the download, confirm Ready to Install. RadioMaster+ exits and the
            installer opens. Follow its prompts and verify the destination is the copy
            you use. For a portable copy, choose its existing portable folder, not a
            different installation. Keep the entire application folder together.

            Reopen the installed copy and use Help > About RadioMaster+ to verify its
            version. Building or downloading a new version elsewhere does not replace a
            still-running old executable. Finish recordings before closing for an update.
        """),
        _topic("Updating the YouTube Library", """
            Help > Update YouTube Library updates the bundled yt-dlp component used for
            resolving YouTube media and downloads. Wait for the result message, then
            retry the operation that failed. The library update needs a connection and
            write access to its tool location.

            Settings > Advanced can enable background updates, checked at most weekly
            on startup. This does not install a new RadioMaster+ version or alter the
            version shown in About. Use Check for Updates for the application itself.
        """),
        _topic("Portable Mode and Backups", """
            A writable application folder keeps application-owned data in its data
            folder. When that location is not writable, the application uses per-user
            Windows locations. Portable installation is intended to keep the executable,
            supporting folders, settings, databases, and default media locations together.

            Before moving or backing up a portable copy, stop recordings and exit the
            application. Copy the complete application folder, including data and
            _internal. Destinations you explicitly chose outside it must be backed up
            separately. Relative app-contained media paths can survive a drive-letter change.

            OPML export is useful for podcast subscriptions, but it is not a backup of
            Favorites, custom stations, schedules, bookmarks, shortcuts, themes, media,
            or listening progress. Keep a full data backup for those items.
        """),
        _topic("Files, Storage, and Logs", """
            Download Location, Podcast Download Location, and Recording Location are
            shown in their respective Settings categories. They can point to different
            folders. Changing a setting does not relocate files already saved elsewhere.

            Portable defaults live beneath the app's data folder, with separate folders
            for configuration, databases, cache, logs, downloads, podcasts, and recordings.
            Standard protected-folder installations use per-user Windows locations.
            Settings > Advanced shows the actual log location for the running copy.

            Do not remove _internal or bundled tools as if they were download history.
            Removing History entries does not reclaim the saved media's disk space.
            Use file management to organize media and check free space, then remember
            that moving a file can make an old History entry unable to find it.
        """),
        _topic("Troubleshooting", """
            No sound: check Play/Pause, Volume, Mute, Pan, Sound Output Device, Windows
            volume, and the selected device. Try a known local file and another station.
            A problem limited to one source is different from no audio anywhere.

            Radio disconnects: read the status/error, check the connection and Network
            settings, and review Radio reconnection limits. Try a different stream and
            use Station Health Check. A dead or restricted station may require waiting
            for its operator rather than changing playback controls.

            Missing bitrate or track title: the station may not supply it, or detection
            may fail. Reported format is a fallback, not a verified measurement. Read
            the status bar as well as the station results and confirm the running version.

            YouTube playback/download failure: update the YouTube library, check the
            link and connection, then retry. Missing downloaded file: check its configured
            folder and whether it was moved. Failed tasks can be retried from History.

            Rate disabled on Radio is intentional. If an effect's preset seems unchanged,
            read Using the Effects Menu for backend limitations. If a recording continues
            after Stop, use Stop Recording; playback and recording are independent.
        """),
        _topic("Reporting a Problem and Current Limits", """
            Record the version from Help > About RadioMaster+, the action that failed,
            the expected result, the actual message, and whether the problem happens with
            another source. Mention whether you use a portable or standard installation,
            the playback type, and your screen reader if relevant.

            If more detail is needed, choose Debug in Settings > Advanced, reproduce
            the issue, and obtain the log from the displayed location. Return to Info
            afterward. Review logs before sharing them because source addresses and
            filenames may contain information you do not intend to publish.

            Current limits are explained with the related features: global search scopes,
            audiobook Library/bookmark navigation, DAISY synchronization, non-DAISY TTS,
            archive-member playback, some BASS effect parameters, theme-file import, and
            end-of-track/end-of-playlist sleep modes. Their presence in the interface
            should not be mistaken for completed functionality.
        """),
        _topic("Requirements, Version, and Credits", """
            RadioMaster+ is a Windows desktop application. The packaged build includes
            its Python runtime and supporting media tools, so a separate Python or
            FFmpeg installation is not needed for normal use. Use a compatible Windows
            audio device, sufficient free storage, and internet access for online features.

            Help > About RadioMaster+ reports the application version and credits.
            Help > Release Notes describes changes in the installed build. External
            services and bundled components have their own availability and terms.
            The distribution includes LICENSE and THIRD_PARTY_NOTICES for licensing
            and component attribution.
        """),
    ]),
]


_EFFECT_DESCRIPTIONS = {
    "echo": "Echo adds delayed repeats. Delay sets spacing; Decay controls repetition strength; In Gain and Out Gain set signal levels in the editor. On BASS, Out Gain controls the effect mix and In Gain is not applied.",
    "equalizer": "Equalizer adjusts frequency balance. Lower frequencies affect bass, middle frequencies affect voice/body, and higher frequencies affect brightness.",
    "reverb": "Reverb adds room ambience. Room Size, Decay, and Mix control the space, tail, and effect level. Small Room is shorter and drier than Stadium; changing these presets updates active BASS reverb.",
    "dynamic_range": "Dynamic Range reduces the difference between loud and quiet material. Threshold, Ratio, Knee, Attack, and Release describe when and how compression responds. On BASS this enables the shared Compressor, whose settings are used instead of a separate Dynamic Range parameter set. Use Compressor for adjustable native compression.",
    "pitch_tempo": "Pitch/Tempo Shift separates pitch in cents from tempo. Negative cents lower pitch; positive cents raise it. Tempo 1.0 is normal. Live radio rate limitations still apply.",
    "chorus": "Chorus combines modulated copies for a fuller sound. Its controls are Delay, Decay, Speed, and Depth.",
    "compressor": "Compressor reduces loud peaks. Threshold, Ratio, Attack, and Release control response; Makeup Gain raises output afterward.",
    "distortion": "Distortion adds a rougher sound. The editor exposes Bit Depth and Mix; lower bit depth requests stronger digital degradation.",
    "flanger": "Flanger mixes a changing short delay with the original signal. Delay, Depth, and Speed control its sweep.",
    "gargle": "Gargle applies rhythmic amplitude modulation. Rate sets the pulse frequency; Depth requests its strength. BASS applies Rate but does not offer a corresponding Depth control, so Depth is not applied on that playback path.",
}

# Include every effect, control range, and built-in preset from the actual UI
# catalogue rather than maintaining a second list that can become stale.
effect_topics = next(topics for category, topics in MANUAL_SECTIONS if category == "Audio Effects")
for effect_id in EFFECT_IDS:
    controls = "\n".join(
        f"- {label}: {minimum:g} to {maximum:g}; initial value {default:g}."
        for label, _key, minimum, maximum, default in PARAM_DEFS[effect_id]
    )
    presets = "; ".join(BUILTIN_PRESETS.get(effect_id, {}))
    effect_topics.append(_topic(
        f"{EFFECT_LABELS[effect_id]} Reference",
        f"Open Effects > {EFFECT_LABELS[effect_id]}.\n\n"
        f"{_EFFECT_DESCRIPTIONS[effect_id]}\n\n"
        f"Built-in presets: {presets}.\n\nParameter editor controls:\n{controls}\n\n"
        "Use On/Off, select a preset, or open the Manager to make a custom preset. "
        "See Using the Effects Menu for playback-path limitations and Creating and "
        "Managing Effect Presets for saving and applying changes.",
    ))

USER_MANUAL_TOPICS = [topic for _category, topics in MANUAL_SECTIONS for topic in topics]
TOPIC_CATEGORIES = {title: category for category, topics in MANUAL_SECTIONS for title, _body in topics}
CATEGORY_ORDER = [category for category, _topics in MANUAL_SECTIONS]
