"""Small offline suite inventory and opt-in live memory-router eval."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

import yaml


async def evaluate_memory_routing(router, dataset: list[dict]):
    from langchain_core.messages import HumanMessage, SystemMessage

    prompt = (
        "Route each request with one memory_intent and any necessary memory_reads. Choose exactly one intent: "
        "entity_read (a question about a stored current fact), episode_read (a past event or decision), "
        "knowledge_read (general reference knowledge), entity_update_and_episode_write (a user reports a durable current-fact update), "
        "procedural_write (an explicit standing instruction), memory_forget (an explicit request to forget/delete/remove/clear/erase stored memory), "
        "pattern_read (recall a stated recurring preference or behavior), "
        "or none (no personal memory read or write). memory_reads may contain only episode, knowledge, or pattern. "
        "For episode/knowledge/pattern reads, include a concise search query in memory_reads. For entity reads and writes, "
        "use the always-injected current entity store and return no routed read. Never infer personal facts from a general question.\n\n"
        "Examples:\n"
        "User: What is my current salary? => entity_read, no memory_reads.\n"
        "User: What did we decide last April? => episode_read, one episode read with the date and decision query.\n"
        "User: How does a SIP work? => knowledge_read, one knowledge read.\n"
        "User: I just changed jobs to TCS. => entity_update_and_episode_write, no routed read.\n"
        "User: Never recommend equity to me again. => procedural_write, no routed read.\n"
        "User: Forget the rule about Aditya. => memory_forget, no routed read.\n"
        "User: Delete the email draft. => none.\n"
        "User: I'm worried about market volatility. => pattern_read, one pattern read.\n"
        "User: What is the average salary for a Python developer? => none.\n"
        "User: What is equity investing? => none."
    )
    results = []
    for case in dataset:
        examples = [(text, case["operation"], case.get("store")) for text in case["utterances"]]
        for negative in case.get("negatives", []):
            if isinstance(negative, str):
                examples.append((negative, "none", None))
            else:
                examples.append((negative["utterance"], negative.get("operation", "none"), negative.get("store")))
        for utterance, expected, expected_store in examples:
            decision = await router.ainvoke([
                SystemMessage(content=prompt),
                HumanMessage(content=utterance),
            ])
            intent = getattr(decision, "memory_intent", None)
            reads = getattr(decision, "memory_reads", [])
            store = (reads[0].get("store") if isinstance(reads[0], dict) else getattr(reads[0], "store", None)) if reads else None
            reason = ""
            if intent != expected:
                reason = "intent mismatch"
            elif expected_store is not None and store != expected_store:
                reason = "memory store mismatch"
            elif expected == "none" and reads:
                reason = "unexpected memory read"
            passed = not reason
            results.append({
                "id": case["id"], "utterance": utterance,
                "expected": expected, "actual": intent,
                "expected_store": expected_store, "actual_store": store,
                "reason": reason, "pass": passed,
            })
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

    router = ChatOpenAI(
        model=settings["aux"], api_key=api_key, temperature=0,
        max_completion_tokens=512, timeout=30, max_retries=1,
    ).with_structured_output(RouteDecision)
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
            print(
                f"{status}\t{result['id']}\t{result['expected']}\t{result['actual']}\t"
                f"{result['expected_store'] or '-'}\t{result['actual_store'] or '-'}\t"
                f"{result['reason'] or '-'}\t{result['utterance']}"
            )
        print(f"memory-routing: {len(results)-len(failures)}/{len(results)} pass")
        raise SystemExit(1 if failures else 0)
    print(f"Loaded {cases} cases for suite {args.suite}; no model calls were made.")


if __name__ == "__main__":
    main()
