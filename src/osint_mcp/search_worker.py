"""Isolate synchronous metasearch so timeouts can stop its background threads."""

import contextlib
import json
import sys

from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException, TimeoutException


def search(query: str, limit: int) -> dict:
    try:
        rows = DDGS(timeout=10).text(query, max_results=limit, backend="auto")
        return {
            "results": [
                {
                    "url": row["href"],
                    "title": row.get("title", "")[:1000],
                    "snippet": row.get("body", "")[:4000],
                }
                for row in rows[:limit]
            ]
        }
    except RatelimitException:
        return {"error": "Keyless search was rate limited.", "status": "blocked"}
    except TimeoutException:
        return {"error": "Keyless search timed out.", "status": "error"}
    except DDGSException:
        return {
            "error": "Keyless engines returned no usable response; absence is unconfirmed.",
            "status": "unknown",
        }


def main():
    request = json.load(sys.stdin)
    # Only our JSON goes to stdout, even if a dependency prints diagnostics.
    with contextlib.redirect_stdout(sys.stderr):
        result = search(request["query"], request["limit"])
    json.dump(result, sys.stdout)


if __name__ == "__main__":
    main()
