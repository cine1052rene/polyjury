"""Generate today's case for one or more cities.

    python scripts/generate_case.py                 # all cities, today
    python scripts/generate_case.py --city london --date 2026-09-14
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.casegen import generate_case  # noqa: E402
from engine.cities import CITIES  # noqa: E402
from engine.facts import gather_facts  # noqa: E402
from engine.store import save_case  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", choices=sorted(CITIES), action="append")
    parser.add_argument("--date", type=dt.date.fromisoformat, default=dt.date.today())
    parser.add_argument("--attempts", type=int, default=2)
    args = parser.parse_args()

    failures = 0
    for city_id in args.city or sorted(CITIES):
        city = CITIES[city_id]
        t0 = time.time()
        print(f"\n=== {city.name} {args.date} ===", flush=True)
        facts = gather_facts(city, args.date, log=lambda m: print(m, flush=True))
        print(f"  definitive facts: {len(facts)}", flush=True)
        case = generate_case(city, facts, args.date, attempts_per_fact=args.attempts,
                             log=lambda m: print(m, flush=True)) if facts else None
        if case is None:
            failures += 1
            print(f"  !! no fair case for {city.name} ({round(time.time() - t0)}s)", flush=True)
            continue
        path = save_case(case)
        print(f"  saved {path.name} ({round(time.time() - t0)}s): {case['public']['title']} "
              f"-> culprit {case['hidden']['culprit']}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
