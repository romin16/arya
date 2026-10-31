import os


# CI and local pytest runs fail closed if un-tokenized PII reaches an outbound
# payload. Individual tests may override this with monkeypatch when testing
# production re-tokenization behavior.
os.environ["PII_EGRESS_STRICT"] = "1"
