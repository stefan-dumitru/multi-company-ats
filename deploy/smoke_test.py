"""Post-deploy smoke test: is the version that just shipped really up and serving?

Run by the deploy workflow after Railway reports a deployment as live:

    python deploy/smoke_test.py https://staging.example.com

Standard library only, so the workflow needs no extra installs. Exit codes: 0 = healthy,
1 = a check failed, 2 = bad command line.
"""

import argparse
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence

# Appears in frontend/index.html. Proves the built React app (not just the API) is being served.
FRONTEND_MARKER = "<title>ATS</title>"


class SmokeTestFailed(Exception):
    """A check did not pass before the deadline."""


def _fetch(url: str, timeout: float) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "ats-smoke-test"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(65536).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        # 4xx/5xx still carry a status code, which is all the callers report.
        return error.code, ""


def _check(base_url: str, path: str, timeout: float, is_good: Callable[[str], bool]) -> str | None:
    """Return None if the endpoint is good, otherwise a short reason (never the response body)."""
    try:
        status, body = _fetch(base_url + path, timeout)
    except TimeoutError:
        return f"GET {path} timed out after {timeout:g}s"
    except urllib.error.URLError as error:
        if isinstance(error.reason, TimeoutError):
            return f"GET {path} timed out after {timeout:g}s"
        return f"GET {path} could not connect"
    except OSError:
        return f"GET {path} could not connect"
    if status != 200:
        return f"GET {path} returned HTTP {status}"
    if not is_good(body):
        # Reported without the body: it could hold stack traces or internal addresses.
        return f"GET {path} returned 200 but not the expected content"
    return None


def run_smoke_test(
    base_url: str,
    *,
    deadline_seconds: float = 120.0,
    request_timeout: float = 10.0,
    retry_interval: float = 5.0,
) -> None:
    """Check /health, /ready and the frontend; retry until all pass or the deadline passes.

    Retries exist because a fresh deployment needs a few seconds before it answers; the deadline
    exists so a broken one fails the pipeline instead of hanging it.
    """
    base_url = base_url.rstrip("/")
    checks = [
        ("/health", lambda body: '"status":"ok"' in body.replace(" ", "")),
        ("/ready", lambda body: '"status":"ready"' in body.replace(" ", "")),
        ("/", lambda body: FRONTEND_MARKER in body),
    ]
    deadline = time.monotonic() + deadline_seconds
    while True:
        failures = [
            reason
            for path, is_good in checks
            if (reason := _check(base_url, path, request_timeout, is_good)) is not None
        ]
        if not failures:
            return
        if time.monotonic() + retry_interval >= deadline:
            # The "/" check fails when the app answers but is not the ATS frontend page.
            failures = [f.replace("GET / returned", "GET / (frontend) returned") for f in failures]
            raise SmokeTestFailed(f"after {deadline_seconds:g}s: " + "; ".join(failures))
        time.sleep(retry_interval)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test a deployed ATS instance.")
    parser.add_argument("url", help="base URL, e.g. https://ats-staging.up.railway.app")
    parser.add_argument("--deadline", type=float, default=120.0, help="seconds to keep retrying")
    parser.add_argument("--request-timeout", type=float, default=10.0, help="seconds per request")
    parser.add_argument("--retry-interval", type=float, default=5.0, help="seconds between tries")
    args = parser.parse_args(argv)

    parsed = urllib.parse.urlparse(args.url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        print(f"Not an http(s) URL: {args.url!r}", file=sys.stderr)
        return 2

    try:
        run_smoke_test(
            args.url,
            deadline_seconds=args.deadline,
            request_timeout=args.request_timeout,
            retry_interval=args.retry_interval,
        )
    except SmokeTestFailed as failure:
        print(f"Smoke test FAILED {failure}", file=sys.stderr)
        return 1
    print(f"Smoke test passed: {args.url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
