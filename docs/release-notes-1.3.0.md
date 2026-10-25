# RadioMaster+ 1.3.0

A large feature release: real crossfade, much better DAISY audiobooks, and the interface in nine languages.

## Playback
- Crossfade now overlaps local playlist tracks: the outgoing track fades out while the next fades in for the duration set in Settings > Playback. Radio, podcasts, video and online streams still change over directly.
- Normalize audio (EBU R128) measures local files in the background on first play and adjusts their volume.
- Dynamic Range now converts its dB threshold correctly; the equalizer uses one filter per band (the 32 and 64 Hz sliders share an 80 Hz filter).
- End of Track and End of Playlist sleep timer modes now work. Live radio stops when the countdown ends.

## Audiobooks
- DAISY 2.02 and DAISY 3 books are read through their navigation and SMIL files: every chapter and page has its own audio file, start point, text and duration.
- New Go to Page, Previous Page and Next Page (with assignable shortcuts), a Bookmarks list with Go To, chapter text with sentence highlighting during Read with TTS, and automatic advance to the next chapter.
- A second speech engine: Windows OneCore voices.

## Interface
- Spanish, French, German, Italian, Portuguese, Russian, Japanese and Chinese (Simplified). The translations are unreviewed drafts; run-time status text and the manual stay in English.

## Everything else
- Save Playlist (M3U8) and opening M3U/M3U8/PLS playlists; playing media from inside ZIP archives.
- First/Previous/Next/Last now work on Media Player, Audiobooks and YouTube. Global search covers podcasts, YouTube, media and audiobooks.
- Upload your subscriptions to gpodder.net; optional Genius and Musixmatch lyrics keys.
- Equalizer window presets persist; cancelling a preset edit restores the sound; the Download History limit skips zero.
- Fixed the minimize-to-tray default and the BASS "already initialized" error code.

## Known limits
- Echo In Gain and Gargle Depth have no equivalent on the BASS engine and remain unapplied.
- The new engine and language features are covered by tests, but the translations and DAISY handling have not been checked by native speakers or against a wide range of real books.
