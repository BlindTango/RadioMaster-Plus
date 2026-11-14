# RadioMaster+ 1.3.3

YouTube videos play to the end, radio no longer freezes the window, and YouTube quality is a setting.

## YouTube
- Videos no longer end abruptly part-way through. The step that combines YouTube's separate video and audio streams now reconnects when the server drops a long or idle connection. Tested against a server that drops every connection: the video ended at 12 s of 40 s before, and ran to 39.9 s after.
- New Settings > Playback > YouTube video quality: Best available, 1080p (default), 720p, 480p or 360p. The very best quality is often 4K, which measured 712 MB for a 10-minute video (124 MB at 1080p) and stalls on ordinary connections. A cap never makes a video fail; the closest available stream is used.
- Playback keeps a usable stream even when yt-dlp prints warnings or exits with an error, finds streams nested in its results, and opens a channel or playlist instead of trying to play it as a video.
- When a video cannot be played, the status bar and error dialog now give yt-dlp's actual reason (for example, a private video or a timeout).

## Radio
- The window no longer freezes while a station is connecting. Volume, pan, speed, effects, Pause and Resume wait at most 0.1 s and are applied when the connection finishes; before, they could block the window for 5 s and then end the audio. Stop abandons a stalled connection immediately.
- The audio engine starts in the background when RadioMaster+ launches.

## Diagnostics
- If the window stops responding for 2 seconds, every thread's stack is written to `ui-stalls.log` in the logs folder, once per freeze. Send that file when reporting a freeze.

## Help
- Updated the in-app release history and Quick Start Guide, and the User Manual's Playback Settings.

## Known limits
- The new quality label is not yet translated; it appears in English in every language.
- One test in the suite (a 50,000-row station-health list) fails intermittently in full runs; it passes on its own.
