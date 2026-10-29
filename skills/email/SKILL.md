---
name: email
description: Search, draft, label, send, and reply to Gmail messages.
tools: gmail_search, gmail_get, gmail_draft, gmail_send, gmail_reply, gmail_labels, gmail_label
---
Search and drafts are read/prepare operations. Sending and replying require approval. Keep email addresses tokenised in model context.

Examples:
- “Find the latest mail from Neha” → search Gmail.
- “Draft a reply” → create a draft and show its summary.
- “Send this email” → ask approval before send.
