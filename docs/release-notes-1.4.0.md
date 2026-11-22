# RadioMaster+ 1.4.0

Regional routing: reach stations that only play in their own country through a VPN you already have.

## Regional routing
- Settings > Network > Switch my VPN to a station's country, with Country Routes. Each country uses ExpressVPN (a region such as `uk-london`), a Tailscale exit node, or custom connect and disconnect commands for another VPN. RadioMaster+ supplies no VPN of its own.
- By default the VPN is switched only when a station refuses you because of your region; "Always before playing" is also available.
- List several servers per country, separated by commas. If a station is still refused, the next server is tried automatically. A broadcaster can block one VPN server and not another in the same country.
- The VPN is put back about 20 seconds after playback stops, when you play a station from another country, and on exit. ExpressVPN's selected region is restored too. The routing waits for ExpressVPN's DNS after connecting.
- A VPN changes the route for the whole computer, not only RadioMaster+.

## Blocked stations
- A station that refuses you because of your region now says so and what to do.
- Station Health Check no longer counts region blocks as dead streams, and Hide All Dead leaves them alone.
- HLS streams whose playlist is open but whose audio is refused are detected (BBC Radio 5 Live's UK stream is one).
- Verify with VPN connects the VPN to each country with a route, tests the blocked stations, and puts the VPN back. Stations that play are confirmed as requiring a VPN; stations that fail on every server are reclassified as dead. Custom stations you added are kept.
- Confirmed stations show "(requires VPN)" after their name in the station lists.

## Custom stations
- Find with Browser: for pages whose player only starts when you press Play. Uses a temporary, muted Chrome or Edge window without your profile or logins.
- Look Up in Directory: matches the website against the Radio Browser catalog already stored on your computer and keeps only streams that play. Nothing you type is sent anywhere.
- Radio Garden station pages are recognised.
- Custom stations can have a country, so routing and the VPN label work for them.

## Known limits
- Tested live with ExpressVPN (connect, switch server, restore) and with Tailscale and custom commands only through simulated commands. Radio Garden links could not be tried from the build machine.
- The proxy setting does not apply to radio audio; only a VPN does.
- A refusal alone does not prove a region block; some hosts refuse stations that are off the air. Verify with VPN settles it.
- The new menu items and labels from 1.3.3 onward are not yet translated.
- One test in the suite (a 50,000-row station-health list) fails intermittently in full runs; it passes on its own.
