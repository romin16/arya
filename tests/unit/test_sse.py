import json
from core.sse import encode_event


def test_sse_event_shape():
    line = encode_event({"chunk": "hello"})
    assert line.startswith("data: ") and line.endswith("\n\n")
    assert json.loads(line[6:]) == {"chunk": "hello"}
