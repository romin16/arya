# Google Workspace MCP bake-off

This time-boxed comparison checked two community servers against the required surfaces: Gmail search/read/draft/send/reply/labels, Calendar event CRUD, Contacts CRUD, OAuth2, and a separate Streamable HTTP endpoint. No Google account or live Google API was used. The comparison used each project's published tool list and pinned source metadata.

## Candidates

| Candidate | Fit | Trade-off |
| --- | --- | --- |
| [`dguido/google-workspace-mcp` 3.4.4](https://github.com/dguido/google-workspace-mcp) | Gmail, Calendar, and Contacts; desktop OAuth; Calendar and Contacts CRUD; Gmail send, draft, read, search, label changes, and deletion. It has broader adoption than the selected project. | Its published tool list has no threaded reply operation and documents stdio use, so it needs a separate stdio-to-HTTP bridge for this Windows-selector architecture. |
| [`snickery/google-accounts-mcp` 0.2.1](https://github.com/snickery/google-accounts-mcp/tree/283988563f9af0c8f4886dde303c5a92d49cf571) | Gmail search/read/thread/draft/send, with `reply_to_message_id` for threaded replies; labels; Calendar event create/read/update/delete; Contacts create/read/update/delete; installed-app OAuth; built-in Streamable HTTP with bearer auth. Its declared Python requirement is 3.12. | The project labels itself beta and had a small public footprint at selection time. Its pinned source binds to `0.0.0.0`; our setup script applies and verifies a one-line loopback bind patch. |

## Selection and pin

Selected `snickery/google-accounts-mcp` **v0.2.1**, resolved to commit `283988563f9af0c8f4886dde303c5a92d49cf571`. Its existing Streamable HTTP transport, bearer authentication, Python 3.12 runtime, and threaded Gmail reply support fit ARYA's separate-process requirement without another bridge process. Contact and Calendar CRUD are exposed directly. Gmail removal is implemented as adding Google's `TRASH` label. The upstream beta status and the local bind patch are material limitations; the patch script refuses to continue if the pinned source no longer matches.

The server runs at `http://127.0.0.1:5003/mcp`. Its OAuth refresh tokens live in the per-user local application data directory, outside the repository. Every Google tool passes through `MCPToolAdapter` for a per-call timeout, one retry on transient errors, and normalized failures. Mail send/reply/trash and Calendar/Contact deletes have `mode: ask` in policy, and the adapter refuses them until Phase 6 supplies the approval flow.

This is a source/tool-surface bake-off, not a live CRUD acceptance test. Adapter, policy, and contract tests use mocked tools; OAuth and account round-trips remain for the manual setup/test step.
