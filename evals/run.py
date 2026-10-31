"""Small offline suite inventory and opt-in live memory-router eval."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import yaml


async def evaluate_memory_routing(router, dataset: list[dict]):
    from langchain_core.messages import HumanMessage, SystemMessage

    prompt = (
        "Classify the user's memory intent as entity_read, episode_read, knowledge_read, "
        "entity_update_and_episode_write, procedural_write, pattern_read, or none. "
        "Set memory_reads to episode/knowledge/pattern only when a read is needed. "
        "Use none for requests that do not concern user memory."
    )
    results = []
    for case in dataset:
        examples = [(text, case["operation"]) for text in case["utterances"]]
        examples.extend((text, "none") for text in case.get("negatives", []))
        for utterance, expected in examples:
            decision = await router.ainvoke([
                SystemMessage(content=prompt),
                HumanMessage(content=utterance),
            ])
            intent = getattr(decision, "memory_intent", None)
            reads = getattr(decision, "memory_reads", [])
            store = getattr(reads[0], "store", None) if reads else None
            expected_store = case.get("store") if expected != "none" else None
            passed = intent == expected and (expected_store is None or store == expected_store)
            results.append({"id": case["id"], "utterance": utterance, "expected": expected, "actual": intent, "pass": passed})
    return results


async def _live_memory_routing(dataset: list[dict]):
    from dotenv import load_dotenv
    from langchain_openai import ChatOpenAI
    import os

    root = Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required for --live")
    settings = yaml.safe_load((root / "config" / "models.yaml").read_text(encoding="utf-8"))
    from core.graph.runtime import RouteDecision

    router = ChatOpenAI(model=settings["aux"], api_key=api_key).with_structured_output(RouteDecision)
    return await evaluate_memory_routing(router, dataset)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="gpt-4o,gpt-4o-mini")
    parser.add_argument("--suite", default="all")
    parser.add_argument("--live", action="store_true", help="Make real provider calls; memory-routing only")
    args = parser.parse_args()
    dataset_dir = Path(__file__).parent / "datasets"
    selected = [dataset_dir / "memory-routing.yaml"] if args.suite == "memory-routing" else list(dataset_dir.glob("*.yaml"))
    datasets = [yaml.safe_load(path.read_text(encoding="utf-8")) for path in selected]
    cases = sum(sum(len(row.get("utterances", [row.get("utterance", "")])) + len(row.get("negatives", [])) for row in data)
                if isinstance(data, list) else len(data) for data in datasets)
    if args.live:
        if args.suite != "memory-routing":
            parser.error("--live currently supports only --suite memory-routing")
        results = asyncio.run(_live_memory_routing(datasets[0]))
        failures = [result for result in results if not result["pass"]]
        for result in results:
            status = "PASS" if result["pass"] else "FAIL"
            print(f"{status}\t{result['id']}\t{result['expected']}\t{result['actual']}\t{result['utterance']}")
        print(f"memory-routing: {len(results)-len(failures)}/{len(results)} pass")
        raise SystemExit(1 if failures else 0)
    print(f"Loaded {cases} cases for suite {args.suite}; no model calls were made.")


if __name__ == "__main__":
    main()
