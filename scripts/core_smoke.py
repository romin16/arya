"""Manual SSE-contract smoke test for a running ARYA core."""
from __future__ import annotations

import argparse
import json

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:5000/chat")
    parser.add_argument(
        "--message",
        default="Reply with exactly: core ready. Do not use tools.",
        help="A request for ARYA; the default asks for a text-only reply.",
    )
    options = parser.parse_args()
    events: list[dict] = []
    with httpx.Client(timeout=180) as client:
        with client.stream(
            "POST",
            options.url,
            json={"message": options.message, "session_id": None, "user_id": "smoke-test"},
        ) as response:
            response.raise_for_status()
            if "text/event-stream" not in response.headers.get("content-type", ""):
                raise RuntimeError("Core did not return text/event-stream")
            for line in response.iter_lines():
                if line.startswith("data: "):
                    event = json.loads(line[6:])
                    events.append(event)
                    print(json.dumps(event, ensure_ascii=False))

    if not events or "session_id" not in events[0]:
        raise SystemExit("SSE stream did not start with a session_id event")
    if not events[-1].get("done"):
        raise SystemExit("SSE stream did not end with done")


if __name__ == "__main__":
    main()
