"""
Measure how often the sentiment label agrees with the reviewer's own vote
(Steam's voted_up field: Recommended or Not recommended).

Usage (from the project root, after running score_sentiment.py):
    python backend/scripts/evaluate_sentiment.py        # all games
    python backend/scripts/evaluate_sentiment.py 620    # one game
"""

import argparse
import os

import psycopg
from dotenv import load_dotenv

LABELS = ("positive", "neutral", "negative")

COUNTS_SQL = """
    SELECT voted_up, sentiment_label, count(*)
    FROM reviews
    WHERE %(app_id)s::int IS NULL OR app_id = %(app_id)s
    GROUP BY voted_up, sentiment_label
"""


def pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f}%" if whole else "-"


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare sentiment labels to Steam's voted_up.")
    parser.add_argument("app_id", type=int, nargs="?", help="only evaluate this game (default: all games)")
    args = parser.parse_args()

    load_dotenv()  # finds the .env file in the project root
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is not set. Copy .env.example to .env first.")

    # counts[voted_up][label] = number of reviews; label None means not scored yet
    counts = {True: {}, False: {}}
    with psycopg.connect(database_url) as conn:
        for voted_up, label, n in conn.execute(COUNTS_SQL, {"app_id": args.app_id}):
            counts[voted_up][label] = n

    unscored = counts[True].pop(None, 0) + counts[False].pop(None, 0)
    up = sum(counts[True].values())
    down = sum(counts[False].values())
    total = up + down
    scope = f"app {args.app_id}" if args.app_id else "all games"
    if total == 0:
        raise SystemExit(f"No scored reviews for {scope}. Run score_sentiment.py first.")

    agree = counts[True].get("positive", 0) + counts[False].get("negative", 0)
    neutral = counts[True].get("neutral", 0) + counts[False].get("neutral", 0)

    print(f"Comparing {total:,} scored reviews ({scope})\n")

    # Each row: how the model labeled the reviews that got that Steam vote (rows add up to 100%).
    print(f"{'Steam vote':<24}{'Model: positive':>16}{'neutral':>10}{'negative':>10}")
    for name, vote, n in (("Recommended", True, up), ("Not recommended", False, down)):
        cells = [pct(counts[vote].get(label, 0), n) for label in LABELS]
        print(f"{f'{name} ({n:,})':<24}{cells[0]:>16}{cells[1]:>10}{cells[2]:>10}")

    print()
    print(f"Agreement:                   {pct(agree, total):>6}  "
          "(positive = Recommended, negative = Not recommended; neutral counts as a miss)")
    if neutral < total:
        print(f"Agreement, neutral excluded: {pct(agree, total - neutral):>6}  "
              f"({neutral:,} neutral reviews left out)")
    majority = "Recommended" if up >= down else "Not recommended"
    print(f"Baseline:                    {pct(max(up, down), total):>6}  "
          f"(what always guessing \"{majority}\" would score)")

    if unscored:
        print(f"\nNote: {unscored:,} reviews aren't scored yet and were left out. "
              "Run score_sentiment.py to include them.")


if __name__ == "__main__":
    main()
