# RadioMaster+ 1.2.1

This patch fixes playback and Continue Listening issues in the Quill Radio additions.

## Changes

- Fixed the per-show speed-up shortcut and restored normal speed for shows saved at 1.0 times.
- Restricted per-show speed adjustments to the current podcast episode while playing or paused.
- Made repeated Jump Back presses seek farther back in the active buffer.
- Prevented delayed jumps from switching a newly selected station and kept live playback running when the buffer is too short.
- Converted incoming audio to MP3 for the timeshift buffer, including AAC streams.
- Excluded completed items with known durations from Continue Listening and preserved episode durations from feeds.
- Updated the offline User Manual, Quick Start Guide, and in-app release notes.

## Usage notes

The first Jump Back press begins collecting audio and needs about 15 to 20 seconds before buffer playback starts. It cannot recover audio from before that press. Continue Listening Resume currently requires a local file.

## Validation

Regression coverage includes repeated jumps, station switches, completed items, episode durations, normal-speed shows, and stale podcast speed controls. GUI tests are run in separate processes to avoid application-lifecycle interference.
