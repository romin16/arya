---
name: spotify
description: Play, pause, resume, and navigate Spotify music.
tools: spotify_play, spotify_pause, spotify_resume, spotify_next, spotify_previous
---
Use the device tools for every playback change. `spotify_pause` and `spotify_resume` are distinct idempotent actions.

Examples:
- “Play Daft Punk” → `spotify_play(query="Daft Punk")`.
- “Pause it” → pause the current track.
- “Next song” → advance once.
