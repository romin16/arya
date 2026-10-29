# Migration map

| Legacy component | Planned replacement | Current state |
|---|---|---|
| n8n orchestrator and sub-workflows | Custom LangGraph state graph and typed tools | Core graph not connected |
| Flask desktop server and agents | Authenticated FastMCP device process with serial executor | API shell only |
| Flask voice server and CLI | Separate FastAPI voice service | Provider-free API shell |
| n8n chat memory and old Supabase stores | PostgreSQL checkpointing plus five fresh memory stores | Schema only; no import |
| HTML frontend contract | Existing `arya.html` unchanged against ports 5000/5001 | Compatibility not yet verified |
| Airtable contacts and removed agents | Google Contacts; removed features stay removed | Google integration not configured |

Legacy source is left untouched in its original Downloads location. No secrets or historical memory are imported.
