# RadioMaster+

A unified media player for Windows with full accessibility support. Stream radio, podcasts, YouTube videos, audiobooks (including DAISY 2.02 and NISO 39.86), and local media files — all from a single accessible interface.

## Features

### Media Playback
- **All audio/video formats** via FFmpeg (MP3, FLAC, OGG, WAV, AAC, Opus, MP4, MKV, AVI, WebM, MOV, and more)
- **Streaming protocols**: HTTP/HTTPS (Icecast/SHOUTcast), HLS, DASH, UDP/RTP
- **Transport controls**: Play, Pause, Stop, Seek, Fast Forward, Rewind, Next/Previous/First/Last Track
- **Real-time effects**: Equalizer (10-band), Dynamic Range, Reverb/Echo, Pitch/Tempo, Crossfade, Volume Normalization — all dynamic, no restart required
- **Volume, Pan, and Playback speed** (0.5x to 3.0x) — also dynamic, no restart required, for audio content (radio, podcasts, audiobooks, local audio, YouTube audio). Video playback still restarts on these changes, since it goes through a separate video-rendering path.
- **Video**: Separate resizable frame with fullscreen support

### Radio
- **Free Radio Browser** integration (30k+ stations)
- **Categories**: Alphabetical, Countries, Languages, Genres, Networks
- **Offline database**: Full station catalog stored in SQLite
- **Custom stations**: Add your own station URLs
- **Stream metadata**: ICY/SHOUTcast parsing for current song info

### Podcasts
- **RSS feed subscription** management
- **Podcast directory** browsing (iTunes/Apple)
- **OPML import/export**
- **gpodder.net** sync
- **Custom feeds**: Add by URL
- **Episode management**: Download for offline, auto-download, play progress

### YouTube & Video Sites
- **yt-dlp** integration for stream extraction
- **Search YouTube** from within the app
- **Download videos** (selectable quality)
- **Download audio-only** (MP3/Opus/FLAC)
- **Playlist support**

### Audiobooks
- **DAISY 2.02** and **DAISY NISO 39.86** support
- **Chapter navigation** with synchronized audio+text
- **Sentence highlighting** for learning disabilities
- **SAPI Text-to-Speech** for books without audio narration
- **Bookmarks** and resume from last position
- **ZIP archive** browsing

### Track Identification
- **AcoustID** fingerprinting (semi-automatic)
- **MusicBrainz** metadata lookup
- **Deezer** track identification
- **Track splitting** from mixed recordings
- **Track renaming** with configurable templates

### Lyrics
- **Auto-lookup** from LRCLib, Lyrics.ovh, Genius, Musixmatch
- **Synced lyrics** (LRC format) with line-by-line highlighting
- **Lyrics cache** in SQLite

### Download Manager
- **Queue-based** concurrent downloads
- **Pause/resume** support
- **Format/quality** selection
- **Download history**

### Recording Scheduler
- **Calendar view** for scheduling
- **Multiple simultaneous recordings** while playing one stream
- **Auto or transcoded format** (stream's native format or user-selected)
- **Recurring schedules** (daily, weekly, custom)
- **Conflict detection** and notifications

### Sleep Timer
Smart timer with countdown, end-of-track, and end-of-playlist options.

### Accessibility (First-Class Citizen)
- **Full keyboard navigation** — every feature accessible without a mouse
- **Screen reader compatible** — all controls have proper accessible names
- **In-app keyboard shortcut editor** — every action assignable to one or more keys
- **Sentence highlighting** with configurable colors
- **Dyslexia-friendly font** option (OpenDyslexic)
- **SAPI TTS / Screen reader coexistence** — user-configurable
- **High contrast support** — respects Windows high contrast mode
- **Customizable themes** with live preview editor

### Customization
- **Theme editor** with live preview (light, dark, custom)
- **Keyboard shortcut editor** with conflict detection
- **Multi-language UI** via gettext/PO files
- **Settings dialog** with 8 categories
- **Portable mode** available via installer

## Installation

### From Installer
Download the latest release from the [Releases page](https://github.com/BlindTango/RadioMaster-Plus/releases) and run the Inno Setup installer. The installer offers:

1. **Installation Mode**: All users (admin) or current user only
2. **Installation Type**: Standard (Start Menu, file associations) or Portable (no registry)
3. **Destination Folder**: Browse to choose install location

### From Source

```bash
# Clone the repository
git clone https://github.com/BlindTango/RadioMaster-Plus.git
cd RadioMaster-Plus

# Install dependencies
pip install -r requirements.txt

# Run the application
python -m src.radiomaster
```

### Building with PyInstaller

```bash
pip install pyinstaller
pyinstaller packaging/radiomaster.spec
```

### Building the Installer

Open `packaging/radiomaster.iss` with Inno Setup 7 and compile.

## Requirements

- **OS**: Windows 10 or later
- **Python**: 3.12+
- **FFmpeg**: Required for playback (bundled with installer)
- **yt-dlp**: Required for YouTube features (bundled with installer)

## Dependencies

| Package | Purpose |
|---|---|
| wxPython | GUI framework |
| yt-dlp | YouTube/video site extraction |
| requests / httpx | HTTP client |
| platformdirs | Cross-platform paths |
| mutagen | Audio metadata |
| pyacoustid | Audio fingerprinting |
| musicbrainzngs | MusicBrainz API |
| feedparser | RSS/Atom feeds |
| apscheduler | Scheduling |
| Pillow | Image handling |
| lxml | XML parsing (DAISY) |
| beautifulsoup4 | HTML parsing (DAISY 2.02) |
| pywin32 | Windows SAPI COM |

## Project Structure

```
RadioMaster+/
├── pyproject.toml
├── requirements.txt
├── src/radiomaster/
│   ├── __main__.py          # Entry point
│   ├── app.py               # Application class
│   ├── main_window.py       # Main window
│   ├── settings_dialog.py   # Settings
│   ├── shortcut_editor.py   # Keyboard shortcuts
│   ├── database/            # SQLite layer
│   ├── engine/              # Playback engine
│   ├── services/            # Business logic
│   ├── ui/                  # UI components
│   ├── utils/               # Utilities
│   └── i18n/               # Translations
├── tests/                   # Test suite
├── resources/               # Icons, themes, shortcuts
└── packaging/              # PyInstaller spec, Inno Setup script
```

## License

MIT
