---
name: whatsapp
description: Read WhatsApp messages and send messages or start a voice call.
tools: whatsapp_send, whatsapp_read, whatsapp_voice_call
---
Sending and voice calls require approval. Never send until approved. Resolve contact names with the contacts interface when needed.

Examples:
- “Read the last five messages from Neha” → `whatsapp_read(contact="Neha", n=5)`.
- “Tell Neha I’m late” → prepare `whatsapp_send`; request approval before execution.
