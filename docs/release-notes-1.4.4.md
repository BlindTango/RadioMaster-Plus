# RadioMaster+ 1.4.4

Scheduling a recording no longer needs a typed stream address.

## Scheduler
- Add Schedule has three buttons beside the URL field:
  - **Use Now Playing** takes the station, podcast episode or audiobook that is playing. A video, or a file on your computer, cannot be scheduled, and the button explains that.
  - **Choose Station** lists your favorites and custom stations; type part of a name and choose Search to look through the whole station catalog (favorites first, no repeats).
  - **Choose Podcast Episode** lets you pick one of your subscribed podcasts, then one of its episodes (newest first; episodes with no online audio address are left out).
- Each pick fills in the URL, the Source Type and the Title, then moves focus to Title so a screen reader reads what was filled in. A title you typed yourself is never replaced; one filled in by an earlier pick is.
- The URL can still be typed or pasted as before. Edit Schedule has the same buttons.
- YouTube is not offered as a source: the scheduler records a stream address with ffmpeg, and a YouTube page address does not work.

## Known limits
- The new buttons and lists were tested but not with a screen reader.
- The new labels and menu items from 1.3.3 onward are not yet translated.
- One test in the suite (a 50,000-row station-health list) fails intermittently in full runs; it passes on its own.
