from pathlib import Path

from evals.run import SUITES, _case_count, _percentile, _suite_cases


def test_eval_runner_loads_all_suites_and_tool_routing_coverage():
    dataset_dir = Path(__file__).resolve().parents[2] / "evals" / "datasets"
    assert SUITES == (
        "tool-routing", "memory-routing", "approvals", "persona-tone", "exact-reply", "structured-schemas",
    )
    tool_cases = _suite_cases(dataset_dir, "tool-routing")
    tools = {case["tool"] for case in tool_cases}
    assert {
        "spotify_play", "spotify_pause", "spotify_resume", "spotify_next",
        "open_app", "close_app", "whatsapp_send", "gmail_send", "calendar_create",
        "contacts_search", "get_weather", "web_search",
    } <= tools
    assert {case["utterance"].casefold() for case in tool_cases} >= {"pause it.", "do it again."}
    assert all(_suite_cases(dataset_dir, suite) for suite in SUITES if suite != "structured-schemas")
    memory = _suite_cases(dataset_dir, "memory-routing")
    assert _case_count("memory-routing", memory) == sum(
        len(case.get("utterances", [])) + len(case.get("negatives", [])) for case in memory
    )


def test_percentile_reports_nearest_rank_values():
    assert _percentile([10, 20, 30, 40, 50], 0.50) == 30
    assert _percentile([10, 20, 30, 40, 50], 0.95) == 50
    assert _percentile([], 0.95) == 0
