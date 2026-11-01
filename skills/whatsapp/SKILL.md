---
name: whatsapp
description: Send WhatsApp messages or start a voice call.
tools: whatsapp_send, whatsapp_voice_call
---
For a requested message or voice call, call `whatsapp_send` or `whatsapp_voice_call`; the code policy gate automatically asks for approval before execution. Never claim the message was sent or call connected until the tool result confirms success. Resolve contact names with the contacts interface when needed.

Examples:
- “Tell Neha I’m late” → call `whatsapp_send`; the code policy gate requests approval automatically.
