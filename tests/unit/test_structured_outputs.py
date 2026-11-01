import warnings

from langchain_openai import ChatOpenAI

from core.graph.runtime import STRUCTURED_OUTPUT_MODELS


def _assert_openai_strict_schema(model):
    schema = model.model_json_schema()

    def walk(node, path="#"):
        assert "default" not in node, f"default is not allowed at {path}"
        if node.get("type") == "object":
            properties = node.get("properties", {})
            assert node.get("additionalProperties") is False, path
            assert set(node.get("required", [])) == set(properties), path
        if node.get("type") == "array":
            items = node.get("items")
            assert isinstance(items, dict) and items, path
            assert "additionalProperties" not in items or items["additionalProperties"] is False
        for key, value in node.items():
            if isinstance(value, dict):
                walk(value, f"{path}/{key}")
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    if isinstance(item, dict):
                        walk(item, f"{path}/{key}/{index}")

    walk(schema)
    definitions = schema.get("$defs", {})
    refs = []

    def find_refs(node):
        if isinstance(node, dict):
            if "$ref" in node:
                refs.append(node["$ref"])
            for value in node.values():
                find_refs(value)
        elif isinstance(node, list):
            for value in node:
                find_refs(value)

    find_refs(schema)
    assert all(ref.startswith("#/$defs/") and ref.split("/")[-1] in definitions for ref in refs)
    return schema


def test_every_core_structured_output_model_is_openai_strict_compatible():
    for model in STRUCTURED_OUTPUT_MODELS:
        _assert_openai_strict_schema(model)


def test_langchain_builds_each_strict_response_format_without_schema_warnings():
    llm = ChatOpenAI(model="gpt-4o-mini", api_key="offline-schema-test")
    with warnings.catch_warnings(record=True) as observed:
        warnings.simplefilter("always")
        for model in STRUCTURED_OUTPUT_MODELS:
            llm.with_structured_output(model, method="json_schema", strict=True)
    invalid = [warning for warning in observed if "Invalid schema" in str(warning.message)]
    assert not invalid, "; ".join(str(warning.message) for warning in invalid)
