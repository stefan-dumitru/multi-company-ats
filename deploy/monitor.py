"""Scheduled health check: is the background worker alive, and has any job given up recently?

Run hourly by .github/workflows/monitor.yml, from the repo root:

    python -m deploy.monitor https://staging.example.com https://production.example.com

Standard library only. Exit codes: 0 = all healthy, 1 = a problem was found (the workflow turns
red and GitHub emails the repository owner), 2 = bad command line.
"""

import argparse
import sys
import time
import urllib.parse
from collections.abc import Sequence

from deploy.smoke_test import _check


def _is_ok(body: str) -> bool:
    return '"status":"ok"' in body.replace(" ", "")


def run_monitor(
    base_urls: Sequence[str],
    window_minutes: int,
    *,
    deadline_seconds: float = 60.0,
    request_timeout: float = 10.0,
    retry_interval: float = 5.0,
) -> list[str]:
    """Return one short message per failing check, or an empty list when all is well.

    A failing check is retried until the deadline so a single network hiccup cannot raise an
    alert; a check that is still failing at the deadline is a real problem.
    """
    checks = [
        "/health/worker",
        f"/health/jobs?since_minutes={window_minutes}",
    ]
    problems: list[str] = []
    for base_url in base_urls:
        base_url = base_url.rstrip("/")
        for path in checks:
            deadline = time.monotonic() + deadline_seconds
            while True:
                reason = _check(base_url, path, request_timeout, _is_ok)
                if reason is None:
                    break
                if time.monotonic() + retry_interval >= deadline:
                    problems.append(f"{base_url}: {reason}")
                    break
                time.sleep(retry_interval)
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check worker liveness and failed jobs.")
    parser.add_argument("urls", nargs="+", help="base URLs, e.g. https://ats.up.railway.app")
    parser.add_argument(
        "--window-minutes",
        type=int,
        required=True,
        help="alert on jobs that gave up within this many minutes (a bit over the schedule)",
    )
    parser.add_argument("--deadline", type=float, default=60.0, help="seconds to keep retrying")
    parser.add_argument("--request-timeout", type=float, default=10.0, help="seconds per request")
    parser.add_argument("--retry-interval", type=float, default=5.0, help="seconds between tries")
    args = parser.parse_args(argv)

    for url in args.urls:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            print(f"Not an http(s) URL: {url!r}", file=sys.stderr)
            return 2

    problems = run_monitor(
        args.urls,
        args.window_minutes,
        deadline_seconds=args.deadline,
        request_timeout=args.request_timeout,
        retry_interval=args.retry_interval,
    )
    if problems:
        print("MONITOR FOUND PROBLEMS:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    print(f"Monitor: all healthy ({len(args.urls)} environment(s))")
    return 0


if __name__ == "__main__":
    sys.exit(main())
