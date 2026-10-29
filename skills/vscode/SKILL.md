---
name: vscode
description: Open VS Code folders and files, search, format, and run commands.
tools: vscode_open, vscode_open_file, vscode_search, vscode_run_command, vscode_format
---
Terminal commands require approval. Search and formatting may run automatically.

Examples:
- “Open my project” → `vscode_open(folder=...)`.
- “Search for TODO” → `vscode_search(term="TODO")`.
- “Run the build” → ask approval for `vscode_run_command`.
