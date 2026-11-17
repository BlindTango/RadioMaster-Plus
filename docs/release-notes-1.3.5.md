# RadioMaster+ 1.3.5

YouTube videos recover from a dropped connection and play more smoothly.

## YouTube
- If a video stops part-way because its connection died, RadioMaster+ looks up a fresh stream and resumes from about 2 seconds before the drop, up to 5 times per video. After that the status bar suggests checking your connection or lowering the YouTube video quality. Closing the video window never triggers a resume.
- The 1080p, 720p, 480p and 360p quality choices now prefer H.264 video when YouTube offers it, and fall back to the previous choice otherwise. The player decodes AV1 in software, which at 1080p60 dropped about two thirds of the frames in testing. Best available is unchanged.

## Known limits
- The resume was verified with unit tests and real FFmpeg for the stream flag and seeking, but not against a real YouTube connection drop, which could not be reproduced here (a 7-minute run played cleanly).
- If a video still ends abruptly, `ffplay_last_run.log` in the logs folder records why; please send it.
- The new menu items from 1.3.4 and the quality label from 1.3.3 are not yet translated.
- One test in the suite (a 50,000-row station-health list) fails intermittently in full runs; it passes on its own.
