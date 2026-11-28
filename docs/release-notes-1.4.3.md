# RadioMaster+ 1.4.3

The VPN feature is removed, which fixes a freeze at start-up.

## Removed
- Regional routing (Settings > Network > Switch my VPN to a station's country, Country Routes), Verify with VPN in the Station Health Check, and the "(requires VPN)" label in the station lists. RadioMaster+ no longer connects, switches or disconnects a VPN, and keeps no record of which stations need one.
- Why: RadioMaster+ reconnects the last station when it starts. If that station needed a VPN (BBC Radio 5 Live, for example), the program waited for the VPN to connect and froze. Connect your VPN yourself before choosing a station that only plays in its own country.

## Kept
- A station that refuses you because of your region still says so and what to do, instead of a generic failure.
- The Station Health Check still separates region blocks from dead streams ("Blocked in region"), does not hide them with Hide All Dead, and still detects HLS streams whose playlist opens but whose audio is refused.
- Settings > Network > Identify as (RadioMaster+, Chrome, Firefox or custom), which applies to radio audio too.
- Find with Browser and Look Up in Directory in Add Custom Station, Radio Garden links, and a country for custom stations.

## Notes
- Routing settings saved by earlier versions are removed from the settings file the first time it is loaded and saved.
- The station database drops the table the VPN label used (written by 1.4.0 to 1.4.2) the first time it is opened. No stations, custom stations or Health Check results are touched.
- The help, the User Manual and the release history describe the removal.

## Known limits
- The new menu items and labels from 1.3.3 onward are not yet translated.
- One test in the suite (a 50,000-row station-health list) fails intermittently in full runs; it passes on its own.
