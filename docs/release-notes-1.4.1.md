# RadioMaster+ 1.4.1

Regional routing recovers when a VPN server cannot carry a station.

## Regional routing
- If a station fails to open, or stays at Buffering for 20 seconds without playing, through the connected VPN server, RadioMaster+ now moves to the next server in that country's route. Before, it only did this when the station refused you outright (HTTP 403 or 451).
- A VPN server can reach a broadcaster yet fail to carry its audio. For example, BBC Radio 5 Sports Extra hung through a London server but played through Manchester.
- List several servers per country in Settings > Network > Country Routes, for example `uk-london, uk-manchester, uk-docklands`. A route with a single server has nothing to fall back to.

## Known limits
- Tested with the real radio engine and ExpressVPN: the streams play through Manchester and the audio host. The fallback itself is covered by unit tests; a real London failure could not be forced on demand.
- The proxy setting does not apply to radio audio; only a VPN does.
- The new menu items and labels from 1.3.3 onward are not yet translated.
- One test in the suite (a 50,000-row station-health list) fails intermittently in full runs; it passes on its own.
