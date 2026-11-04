# Evaluation results

Run on 2026-11-04 at commit `ee1a818`, Windows PC, OpenAI API, tools and GUI mocked, model calls live.

Command: `uv run python -m evals.run --models gpt-4o,gpt-4o-mini --live`

| Suite | Model | Pass rate | p50 first chunk (ms) | p95 first chunk (ms) |
|---|---|---|---|---|
| tool-routing | gpt-4o | 18/18 | 848.4 | 1124.1 |
| memory-routing | gpt-4o | 45/46 | 1124.1 | 1430.6 |
| approvals | gpt-4o | 6/6 | 987.6 | 1685.7 |
| persona-tone | gpt-4o | 4/4 | 847.6 | 1122.7 |
| exact-reply | gpt-4o | 1/1 | 931.9 | 931.9 |
| structured-schemas | gpt-4o | 3/3 | 974.8 | 1440.5 |
| tool-routing | gpt-4o-mini | 18/18 | 836.8 | 1163.4 |
| memory-routing | gpt-4o-mini | 46/46 | 922.4 | 1230.4 |
| approvals | gpt-4o-mini | 6/6 | 880.5 | 1793.3 |
| persona-tone | gpt-4o-mini | 4/4 | 656.1 | 677.6 |
| exact-reply | gpt-4o-mini | 1/1 | 1040.2 | 1040.2 |
| structured-schemas | gpt-4o-mini | 3/3 | 1028.1 | 1275.7 |

Failed case: memory-routing, gpt-4o, "Compare equity funds with debt funds." Expected `knowledge_read`, got `none` (answered without a lookup).

Caveats:
- Each suite has between 1 and 46 cases, so the p95 values are based on very few samples and are not statistically meaningful.
- The time measured is the first streamed chunk of the model call in the harness, not a full turn with routing, tools, memory writes and speech synthesis.
- The suites were written by the project author and are regression tests, not accuracy benchmarks.
- Models are configured in `config/models.yaml`.