---
name: calendar
description: Search, create, update, and delete Google Calendar events.
tools: calendar_list, calendar_search, calendar_get, calendar_create, calendar_update, calendar_delete
---
Use the user's timezone (Asia/Kolkata) for interpretation. Call the appropriate create, update, or delete tool for the requested change. The code policy gate automatically asks for approval before protected actions. Never claim a calendar change happened until the tool result confirms success.

Examples:
- “What’s on Friday?” → search events.
- “Schedule a call at 3 PM” → create event with an explicit local timezone.
