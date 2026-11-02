import os


# CI and local pytest runs fail closed if un-tokenized PII reaches an outbound
# payload. Individual tests may override this with monkeypatch when testing
# production re-tokenization behavior.
os.environ["PII_EGRESS_STRICT"] = "1"
# Prevent normal tests from exporting traces to a developer's Langfuse instance.
os.environ["LANGFUSE_TRACING_ENABLED"] = "false"
