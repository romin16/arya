"""Apply the idempotent schema to an explicitly configured PostgreSQL database."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is required (set it in .env)")
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("Install the project dependencies first") from exc
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with psycopg.connect(url) as conn:
        conn.execute(schema)
    print("Schema applied.")


if __name__ == "__main__":
    main()