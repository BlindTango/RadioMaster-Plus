# RadioMaster+ Feature Sign-off Checklist — Quill-Borrowed Features

One pass, top to bottom, checking boxes. Every step says exactly what to press,
exactly what to type, and the one thing that decides pass or fail. Modeled on
Quill Radio's sign-off book.

**Fail means:** it did not happen, or it happened silently, or what you heard
differs from what this file quotes. **A silent success is a fail.** Write down
what you actually heard.

Have a screen reader running and speaking (JAWS or NVDA).

---

## Block L — Launch and startup

**L-01. The launch log exists**
- Do: launch RadioMaster+, then open the launch log (beside a portable copy:
  `data\logs\launch.log`; installed: the per-user data folder's `logs`
  subfolder).
- Pass: the file exists and contains "Launch started" with a timestamp.

**L-02. A startup failure says why**
- Do: temporarily rename the app's `_internal` folder (packaged build), launch.
- Pass: one message reads "RadioMaster+ did not start", says the copy looks
  like it was run from inside a zip without extracting, and walks through
  Extract All. Restore the folder afterward.

**L-03. First run, and Skip**
- Do: launch a copy with no config (fresh data folder).
- Pass: the first-run pages appear, each a text box you can arrow through, and
  **Skip** leaves in one keystroke and never asks again (relaunch to confirm).

---

## Block R — Radio: sources, search, timeshift

**R-01. The Sources section lists its sources**
- Do: Radio tab, open the Station Category choice, choose **Sources**.
- Pass: SomaFM, ACB Media, and Internet Archive are listed.

**R-02. Lazy browse with a count**
- Do: select **SomaFM**.
- Pass: a "Loading..." row first, then real rows, and the status bar says how
  many ("N row(s) from SomaFM").

**R-03. The cache**
- Do: switch to another section, then back to Sources and SomaFM again.
- Pass: instant, no second "Loading...".

**R-04. Offline browsing answers from your own disk**
- Do: turn off the network, select **ACB Media**.
- Pass: its ten streams list instantly.

**R-05. The honest empty**
- Do: still offline, select **Internet Archive** (or force a source failure).
- Pass: a spoken sentence like "X could not be reached" — never a silent
  empty list, never a stuck "Loading...".

**R-06. The row carries its own truth**
- Do: arrow the SomaFM rows.
- Pass: each row speaks its note ("Listener-supported independent radio")
  before Enter is pressed.

**R-07. Search fanout, and one final announcement**
- Do: search `ambient`.
- Pass: catalogue results first; extra-source results arrive labelled with
  their source; the status bar announces when all sources have reported; the
  cursor does not jump when a late group lands.

**R-08. Choose Browse Sources**
- Do: Tools > Choose Browse Sources..., uncheck one source, OK.
- Pass: that source is gone from the Sources list; everything else stays
  put; the status bar says "Browse sources updated."

**R-09. Jump back on live radio**
- Do: play a live station, press the Jump Back 15s button (or its shortcut).
- Pass: audio jumps back 15 seconds; the status bar says "Behind live by 15
  seconds." (or the equivalent); no reconnect, no gap.

**R-10. Caught up to live**
- Do: press Jump Forward 15s repeatedly.
- Pass: at the live edge the app says "Caught up to live." and returns to the
  live stream.

**R-11. Song History**
- Do: with a station playing that publishes ICY titles, Tools > Song History...
- Pass: the dialog lists what played, newest with artist/title/time; Copy,
  Identify, and Search Lyrics each work from the context menu.

---

## Block P — Podcasts

**P-01. Unheard badge**
- Do: subscribe to a show with unplayed episodes.
- Pass: the show's row reads "Title (N unheard)"; playing an episode to the
  end drops the count immediately.

**P-02. Folders**
- Do: context menu on the podcast list > New Folder..., create `Tech`; Move
  to Folder... on a show; Rename Folder...; Delete Folder...
- Pass: each announces its result ("Moved X to Tech."); delete confirms with
  the real count and moves children to the main list.

**P-03. Per-show speed**
- Do: play an episode, press Ctrl+Shift+Up.
- Pass: the status bar says the new speed and "Remembered for this show.";
  replaying the episode later starts at that speed; the global rate slider is
  untouched for other content.

**P-04. Mark All as Played**
- Do: context menu on a show with unheard episodes > Mark All as Played.
- Pass: announces the count; the badge clears; the menu item remains but is
  dimmed — a vanished item is a fail.

**P-05. Continue Listening**
- Do: leave a podcast episode, an audiobook, and a local file each part-played;
  File > Continue Listening...
- Pass: all three listed, newest first, each naming its kind and how far in;
  an opening summary ("3 things you did not finish..."); Resume continues
  from the saved position; Forget This One zeroes the position and leaves the
  file untouched; a moved file's row is quietly absent.

---

## Block T — Tools and stats

**T-01. Catalog Status**
- Do: Tools > Station Catalog Status...
- Pass: sentences with the station count, last updated (relative), and the
  refresh schedule; Update Now runs the existing update flow with progress.

**T-02. Listening Statistics**
- Do: listen for a few minutes, then Tools > Listening Statistics...
- Pass: the dialog opens with a spoken summary ("You have listened for...");
  totals only count actual playing time (pause/stop ends a session).

---

## Sign-off

- Build / version: ______________
- Date: ______________
- Screen reader and version: ______________
- Windows version: ______________
- Blocks run: ______________
- Result: [ ] ship  [ ] ship with the findings below  [ ] do not ship

**For every fail, report three things:** the test id, what was said **word for
word**, and what you expected to hear.