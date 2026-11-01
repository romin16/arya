---
name: email
description: Search, draft, label, send, and reply to Gmail messages.
tools: gmail_search, gmail_get, gmail_thread_get, gmail_draft, gmail_send, gmail_reply, gmail_delete, gmail_labels, gmail_label
---
Search, reading, drafts, sending, replying, and moving mail to Trash are available through their tools. When the user asks to send or reply, call `gmail_send` or `gmail_reply` with the requested content; do not substitute a draft unless the user asked for one. The code policy gate automatically pauses protected actions and asks the user for approval before execution. Never claim an email was sent until the tool result confirms success. Keep email addresses tokenised in model context.

Examples:
- “Find the latest mail from Neha” → search Gmail.
- “Draft a reply” → create a draft and show its summary.
- “Reply to this email” → call `gmail_reply` with the reply content; the code policy gate requests approval automatically.
