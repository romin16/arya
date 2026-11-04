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
        "contacts_search", "get_weather", "web_search", "open_url", "youtube_search",
    } <= tools
    by_id = {case["id"]: case for case in tool_cases}
    assert by_id["youtube_search"]["utterance"] == "Open YouTube and search for lofi hip hop."
    assert by_id["open_url"]["utterance"] == "Open github.com."
    assert by_id["open_unknown_app"]["expected_tool_result"] == {"success": False, "verified": False}
    assert by_id["open_app_notepad"]["tool"] == "open_app"
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
