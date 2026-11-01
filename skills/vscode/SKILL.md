---
name: vscode
description: Open VS Code folders and files, search, format, and run commands.
tools: vscode_open, vscode_open_file, vscode_search, vscode_run_command, vscode_format
---
When the user requests a terminal command, call `vscode_run_command`; the code policy gate automatically asks for approval before it runs. Never claim a command ran until its tool result confirms completion. Search and formatting may run automatically.

Examples:
- “Open my project” → `vscode_open(folder=...)`.
- “Search for TODO” → `vscode_search(term="TODO")`.
- “Run the build” → call `vscode_run_command`; the code policy gate requests approval automatically.
