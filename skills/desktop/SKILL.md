---
name: desktop
description: Open and control desktop apps and basic system functions.
tools: open_app, close_app, set_volume, type_text, take_screenshot, lock_screen, open_downloads, open_documents
---
Use a typed device tool for each desktop action. Never claim success before the device confirms it.

Examples:
- “Open Notepad” → `open_app(app="Notepad")`.
- “Set volume to 30” → `set_volume(level=30)`.
- “Show Downloads” → `open_downloads()`.
