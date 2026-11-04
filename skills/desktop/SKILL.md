---
name: desktop
description: Open and control desktop apps and basic system functions.
tools: open_app, open_url, youtube_search, close_app, set_volume, type_text, take_screenshot, lock_screen, open_downloads, open_documents
---
Use a typed device tool for each desktop action. `open_app` is only for known desktop applications, never websites. Use `open_url` for external HTTP/HTTPS pages and `youtube_search` for YouTube searches. Never claim an app opened unless its result has `verified: true`.

Examples:
- “Open Notepad” → `open_app(app="Notepad")`.
- “Open github.com” → `open_url(url="https://github.com")`.
- “Open YouTube and search for lofi hip hop” → `youtube_search(query="lofi hip hop")`.
- “Set volume to 30” → `set_volume(level=30)`.
- “Show Downloads” → `open_downloads()`.
