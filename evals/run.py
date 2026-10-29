"""Offline dataset sanity runner; model comparison requires configured provider access."""
import argparse
from pathlib import Path
import yaml


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", default="gpt-4o,gpt-4o-mini")
    args = parser.parse_args()
    dataset_dir = Path(__file__).parent / "datasets"
    datasets = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in dataset_dir.glob("*.yaml")]
    cases = sum(map(len, datasets))
    print("model\tpass_rate\tcost_usd\tlatency_ms")
    for model in args.models.split(","):
        print(f"{model}\tNOT_RUN ({cases} cases loaded)\t—\t—")
    print("No model calls were made. Implement eval adapters and configure API access to measure results.")


if __name__ == "__main__":
    main()
