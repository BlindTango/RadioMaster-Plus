# RadioMaster+ 1.4.2

A routed station keeps its VPN while it plays, route editing is easier, and you can choose how RadioMaster+ identifies itself.

## Fixed
- A station routed through your VPN no longer fails about 20 seconds after it starts. The player reports a brief "stopped" at the start of every play, and that scheduled the VPN to be put back after 20 seconds with nothing to cancel it, so the VPN was dropped while the station was still playing. The restore is now cancelled when playback starts and skipped while anything plays. The VPN is still put back about 20 seconds after you stop.

## Regional routing
- Edit Route shows the chosen country's ExpressVPN servers in a checkable list. Check the ones you want and use Move Up and Move Down (or Alt with the Up and Down arrows) to set the order they are tried in. Show servers from all countries lists every server. All 214 ExpressVPN regions are matched to catalog countries; a saved server from another country is kept, not dropped.
- Tailscale routes list the exit nodes on your tailnet in the same kind of list. If a VPN cannot be read, or for custom commands, the text boxes are used as before.
- A server that fails to connect is skipped, so one bad entry no longer stops the ones after it. ExpressVPN region names are read in lowercase.
- Routing writes what it does to `radiomaster.log`. When a station is still refused, the message now says why routing could not help (the VPN could not be switched, no route for that country, the station has no country, or the last server was reached).

## Network
- Settings > Network > Identify as: RadioMaster+ (default), Chrome, Firefox or Custom. It applies to radio audio, video, podcasts, downloads and searches. The radio player previously ignored the old custom user agent. With the default, the radio player keeps its own built-in identification.

## Known limits
- The server list, Move Up and Move Down, and the new choices were tested but not with a screen reader.
- Tailscale and custom-command routing were tested only with simulated commands. The fallback to the next server was verified in unit tests and a live ExpressVPN server switch, not against a real London failure.
- The proxy setting does not apply to radio audio; only a VPN does.
- A refusal alone does not prove a region block; some hosts refuse stations that are off the air. Verify with VPN settles it.
- The new menu items and labels from 1.3.3 onward are not yet translated.
- One test in the suite (a 50,000-row station-health list) fails intermittently in full runs; it passes on its own.
