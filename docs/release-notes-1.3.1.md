# RadioMaster+ 1.3.1

Find radio stream URLs from webpages and recover cleanly from playback failures.

## Webpage stream finder

- Open Radio > Add Custom Station, enter a Webpage URL, and choose Scan Webpage.
- The finder follows listen links, embedded players, audio sources, static player configurations, and M3U, PLS, ASX, and HLS playlists.
- Select a result and choose Use Selected Stream to fill Stream Address, or Copy Stream URL to copy it without saving a station.
- Scans run in the background with time and link limits. Stop Scan and Cancel remain available, and late results cannot update a closed dialog.
- Native controls support keyboard navigation and have screen-reader names.

## Radio playback fixes

- UNISA Radio and other iono.fm `/s/` player links resolve to audio before BASS opens them.
- Stream failures preserve their original BASS error code instead of reporting a misleading error 0.
- Corrected the SSL error constant used by the fallback path.
- Initial stream-open failures stop automatic retries. Error dialogs cannot stack, and another station can be selected after a failure.
- Automatic reconnection still recovers a broadcast that drops after successful playback.

## Help

- Updated the User Manual, Quick Start Guide, in-app release history, and feature sign-off checklist.

## Limits

- Players requiring JavaScript execution or a signed-in browser may not expose a stream. Try a specific Listen Live or embedded-player page if a homepage scan finds nothing.
- Some stream URLs expire and need to be discovered again.
