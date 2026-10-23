"""The smoke test decides whether a deployment is good, so every way it can say "no" is tested.

Each test starts a throwaway local HTTP server that plays the role of the deployed app.
"""

import socket
import threading
import time
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from deploy.smoke_test import SmokeTestFailed, main, run_smoke_test

Response = tuple[int, str]
HEALTHY = {
    "/health": (200, '{"status":"ok"}'),
    "/ready": (200, '{"status":"ready"}'),
    "/": (200, "<html><head><title>ATS</title></head></html>"),
}

# Short timings keep the suite fast; the real defaults are much longer.
FAST = {"deadline_seconds": 1.0, "request_timeout": 0.5, "retry_interval": 0.05}


@pytest.fixture
def serve() -> Iterator[Callable[..., str]]:
    """Start a server; routes map a path to a response, or to a function returning one."""
    servers: list[ThreadingHTTPServer] = []

    def start(routes: dict[str, Response | Callable[[], Response]], delay: float = 0.0) -> str:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                time.sleep(delay)
                route = routes.get(self.path, (404, "not found"))
                status, body = route() if callable(route) else route
                self.send_response(status)
                self.end_headers()
                self.wfile.write(body.encode())

            def log_message(self, *args: object) -> None:
                pass  # keep test output quiet

        class QuietServer(ThreadingHTTPServer):
            def handle_error(self, request: object, client_address: object) -> None:
                pass  # the client hanging up mid-response is exactly what the timeout tests do

        server = QuietServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_port}"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def test_passes_when_every_check_succeeds(serve: Callable[..., str]) -> None:
    run_smoke_test(serve(HEALTHY), **FAST)


def test_fails_when_health_returns_503(serve: Callable[..., str]) -> None:
    url = serve({**HEALTHY, "/health": (503, '{"status":"unavailable"}')})

    with pytest.raises(SmokeTestFailed, match=r"/health.*503"):
        run_smoke_test(url, **FAST)


def test_fails_when_health_is_200_but_the_body_is_not_ok(serve: Callable[..., str]) -> None:
    # A proxy's "200 OK" error page must not count as a healthy app.
    url = serve({**HEALTHY, "/health": (200, "<html>Welcome to nginx</html>")})

    with pytest.raises(SmokeTestFailed, match="/health"):
        run_smoke_test(url, **FAST)


def test_fails_when_the_app_is_not_ready(serve: Callable[..., str]) -> None:
    url = serve({**HEALTHY, "/ready": (503, '{"status":"not ready"}')})

    with pytest.raises(SmokeTestFailed, match=r"/ready.*503"):
        run_smoke_test(url, **FAST)


def test_fails_when_the_frontend_is_not_served(serve: Callable[..., str]) -> None:
    url = serve({**HEALTHY, "/": (200, "<html><title>Something else</title></html>")})

    with pytest.raises(SmokeTestFailed, match="frontend"):
        run_smoke_test(url, **FAST)


def test_waits_for_an_app_that_becomes_healthy(serve: Callable[..., str]) -> None:
    # A fresh deployment needs a few seconds to start answering: early failures must be retried.
    calls = {"count": 0}

    def health() -> Response:
        calls["count"] += 1
        return (503, "starting") if calls["count"] <= 3 else (200, '{"status":"ok"}')

    run_smoke_test(serve({**HEALTHY, "/health": health}), **FAST)

    assert calls["count"] == 4


def test_fails_on_a_response_slower_than_the_request_timeout(serve: Callable[..., str]) -> None:
    url = serve(HEALTHY, delay=1.0)

    with pytest.raises(SmokeTestFailed, match="timed out"):
        run_smoke_test(url, deadline_seconds=0.6, request_timeout=0.2, retry_interval=0.05)


def test_fails_when_nothing_is_listening() -> None:
    # Ask the OS for a free port, then release it: nothing is listening there any more.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]

    # The wording differs by platform (Windows is slow to refuse, so it reports a timeout), so only
    # the fact of failing and the endpoint named are asserted.
    with pytest.raises(SmokeTestFailed, match="/health"):
        run_smoke_test(f"http://127.0.0.1:{free_port}", **FAST)


def test_gives_up_at_the_deadline_instead_of_retrying_forever(serve: Callable[..., str]) -> None:
    url = serve({**HEALTHY, "/health": (503, "down")})
    started = time.monotonic()

    with pytest.raises(SmokeTestFailed):
        run_smoke_test(url, deadline_seconds=0.5, request_timeout=0.2, retry_interval=0.05)

    assert time.monotonic() - started < 3


def test_failure_message_never_contains_the_response_body(serve: Callable[..., str]) -> None:
    # Bodies can hold anything (stack traces, internal addresses); only the status is reported.
    url = serve({**HEALTHY, "/health": (500, "Traceback: SECRET-INTERNAL-DETAIL")})

    with pytest.raises(SmokeTestFailed) as failure:
        run_smoke_test(url, **FAST)

    assert "SECRET-INTERNAL-DETAIL" not in str(failure.value)


def test_command_line_exits_zero_on_success_and_one_on_failure(
    serve: Callable[..., str], capsys: pytest.CaptureFixture[str]
) -> None:
    good = serve(HEALTHY)
    bad = serve({**HEALTHY, "/health": (503, "down")})
    quick = ["--deadline", "0.5", "--request-timeout", "0.3"]

    assert main([good, *quick]) == 0
    assert main([bad, *quick]) == 1
    assert "/health" in capsys.readouterr().err


@pytest.mark.parametrize("bad_url", ["", "ftp://example.com", "example.com", "http://"])
def test_command_line_rejects_a_url_that_is_not_http(bad_url: str) -> None:
    assert main([bad_url]) == 2
