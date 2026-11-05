# RadioMaster+ 1.3.2

Browse subscribed YouTube channels and reach their older uploads.

## Channel browsing

- Selecting a subscription in My Channels loads that channel's videos. Press Enter or choose View Videos to move to the video list, then select a video and press Enter to play it.
- Load More Videos appends older uploads in batches of 100, replacing the previous limit of 30 videos. Continue until the status reports End of channel videos.
- Saved channel IDs use the public uploads playlist, which can include Shorts and archived live uploads. Overlapping pages do not add duplicate videos.
- Fractional video durations are formatted safely instead of interrupting the results list.

## Loading and recovery

- Channel loading runs in the background. Rapid selections are combined, and late results cannot replace a newer channel, search, or playlist.
- Failed requests report an error instead of appearing to be empty channels. View Videos retries a failed first load; Load More Videos retries a later page while preserving the videos already shown.
- Interrupted pages retain partial results and can be retried with Load More Videos instead of incorrectly reporting the end of the channel.
- Moving quickly through subscriptions avoids starting a load for every row. Closing the application prevents outstanding results from updating closed panels.

## Help

- Updated the User Manual, Quick Start Guide, in-app release history, and feature sign-off checklist with channel browsing, pagination, and retry instructions.

## Limits

- Subscriptions are stored locally in RadioMaster+ and do not change your YouTube account.
- Private, removed, region-restricted, or otherwise inaccessible videos may not be available. Use Help > Update YouTube Library if extraction stops working.
