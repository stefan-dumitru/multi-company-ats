"""The monitor decides whether to alert, so every way it can say "no" is tested.

Each test starts throwaway local HTTP servers that play the role of the deployed environments.
"""

import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from deploy.monitor import main, run_monitor

Response = tuple[int, str]
Route = Response | Callable[[], Response]
WINDOW = 65
JOBS = f"/health/jobs?since_minutes={WINDOW}"
HEALTHY = {
    "/health/worker": (200, '{"status":"ok"}'),
    JOBS: (200, '{"status":"ok","failed":0}'),
}

# Short timings keep the suite fast; the real defaults are longer.
FAST = {"deadline_seconds": 0.5, "request_timeout": 0.5, "retry_interval": 0.05}


@pytest.fixture
def serve() -> Iterator[Callable[[dict[str, Route]], str]]:
    servers: list[ThreadingHTTPServer] = []

    def start(routes: dict[str, Route]) -> str:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                route = routes.get(self.path, (404, "not found"))
                status, body = route() if callable(route) else route
                self.send_response(status)
                self.end_headers()
                self.wfile.write(body.encode())

            def log_message(self, *args: object) -> None:
                pass  # keep test output quiet

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_port}"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def test_returns_no_problems_when_worker_is_alive_and_no_job_failed(
    serve: Callable[[dict[str, Route]], str],
) -> None:
    assert run_monitor([serve(HEALTHY)], WINDOW, **FAST) == []


def test_reports_a_dead_worker(serve: Callable[[dict[str, Route]], str]) -> None:
    url = serve({**HEALTHY, "/health/worker": (503, '{"status":"unavailable"}')})

    problems = run_monitor([url], WINDOW, **FAST)

    assert len(problems) == 1
    assert "/health/worker" in problems[0] and "503" in problems[0]


def test_reports_a_job_that_gave_up(serve: Callable[[dict[str, Route]], str]) -> None:
    url = serve({**HEALTHY, JOBS: (503, '{"status":"failing","failed":2}')})

    problems = run_monitor([url], WINDOW, **FAST)

    assert len(problems) == 1
    assert "/health/jobs" in problems[0] and "503" in problems[0]


def test_reports_every_environment_that_has_a_problem(
    serve: Callable[[dict[str, Route]], str],
) -> None:
    good = serve(HEALTHY)
    bad = serve({**HEALTHY, "/health/worker": (503, "{}")})

    problems = run_monitor([good, bad], WINDOW, **FAST)

    assert len(problems) == 1
    assert bad in problems[0]
    assert good not in problems[0]


def test_reports_an_environment_that_cannot_be_reached() -> None:
    problems = run_monitor(["http://127.0.0.1:1"], WINDOW, **FAST)

    assert len(problems) == 2  # both checks fail
    # Depending on the OS, a closed port is refused at once or hangs until the request timeout.
    assert all("could not connect" in p or "timed out" in p for p in problems)


def test_a_check_that_answers_200_without_the_expected_content_is_a_problem(
    serve: Callable[[dict[str, Route]], str],
) -> None:
    url = serve({**HEALTHY, JOBS: (200, "<html>some proxy error page</html>")})

    assert len(run_monitor([url], WINDOW, **FAST)) == 1


def test_a_brief_blip_does_not_raise_an_alert(serve: Callable[[dict[str, Route]], str]) -> None:
    # The first answer is bad, the retry is good: one hiccup must not wake anyone up.
    answers = iter([(503, "{}")])

    def flaky() -> Response:
        return next(answers, HEALTHY["/health/worker"])

    url = serve({**HEALTHY, "/health/worker": flaky})

    assert run_monitor([url], WINDOW, **{**FAST, "deadline_seconds": 2.0}) == []


def test_main_exits_1_with_a_message_on_a_problem(
    serve: Callable[[dict[str, Route]], str], capsys: pytest.CaptureFixture[str]
) -> None:
    url = serve({**HEALTHY, JOBS: (503, '{"status":"failing","failed":1}')})

    code = main(
        [url, "--window-minutes", str(WINDOW), "--deadline", "0.3", "--retry-interval", "0.05"]
    )

    assert code == 1
    assert "/health/jobs" in capsys.readouterr().err


def test_main_exits_0_when_everything_is_healthy(
    serve: Callable[[dict[str, Route]], str], capsys: pytest.CaptureFixture[str]
) -> None:
    code = main([serve(HEALTHY), "--window-minutes", str(WINDOW)])

    assert code == 0
    assert "healthy" in capsys.readouterr().out.lower()


def test_main_rejects_a_url_that_is_not_http(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["ftp://example.com", "--window-minutes", "65"]) == 2
