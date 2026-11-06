"""The release command: the order of steps, the safety checks, and what it refuses to do.

A release moves two services (web, then worker) to the same image and takes both back together.
"""

from pathlib import Path

import pytest

from deploy.railway_api import DeploymentFailed, RailwayError, ServiceState
from deploy.release import main
from deploy.smoke_test import SmokeTestFailed

SHA_NEW = "c" * 40
SHA_OLD = "d" * 40
NEW_IMAGE = f"ghcr.io/stefan-dumitru/multi-company-ats:{SHA_NEW}"
OLD_IMAGE = f"ghcr.io/stefan-dumitru/multi-company-ats:{SHA_OLD}"
OLDER_WORKER_IMAGE = f"ghcr.io/stefan-dumitru/multi-company-ats:{'e' * 40}"
TOKEN = "super-secret-token-value"
WEB, WORKER = "svc-web", "svc-worker"
APP_URL = "https://ats-staging.example.com"


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.images: dict[str, str | None] = {WEB: OLD_IMAGE, WORKER: OLD_IMAGE}
        # Make one named service fail at one named step: ("svc-worker", "wait") -> error
        self.failures: dict[tuple[str, str], Exception] = {}

    def _maybe_fail(self, service_id: str, step: str) -> None:
        if (service_id, step) in self.failures:
            raise self.failures[(service_id, step)]

    def get_service_state(self, environment_id: str, service_id: str) -> ServiceState:
        self.calls.append(f"{service_id}:state")
        return ServiceState(self.images[service_id], "dep-0", "SUCCESS")

    def set_image(self, environment_id: str, service_id: str, image: str) -> None:
        self.calls.append(f"{service_id}:set_image:{image}")
        self._maybe_fail(service_id, "set_image")
        self.images[service_id] = image

    def deploy(self, environment_id: str, service_id: str) -> str:
        self.calls.append(f"{service_id}:deploy")
        return f"dep-{service_id}"

    def wait_for_deployment(self, deployment_id: str, *, timeout: float) -> None:
        self.calls.append(f"wait:{deployment_id}")
        service_id = deployment_id.removeprefix("dep-")
        self._maybe_fail(service_id, "wait")


class Harness:
    """Runs main() with a fake Railway client and fake checks, and collects the effects."""

    def __init__(self, tmp_path: Path) -> None:
        self.client = FakeClient()
        self.smoke_calls: list[str] = []
        self.smoke_error: Exception | None = None
        self.worker_checks: list[tuple[str, str | None]] = []
        self.worker_check_error: Exception | None = None
        self.github_output = tmp_path / "github_output.txt"
        self.env = {
            "RAILWAY_TOKEN": TOKEN,
            "RAILWAY_ENVIRONMENT_ID": "env-1",
            "RAILWAY_SERVICE_ID": WEB,
            "RAILWAY_WORKER_SERVICE_ID": WORKER,
            "APP_URL": APP_URL,
            "GITHUB_OUTPUT": str(self.github_output),
        }
        self.clients_created = 0

    def make_client(self, token: str) -> FakeClient:
        self.clients_created += 1
        return self.client

    def smoke(self, url: str, deadline_seconds: float) -> None:
        self.smoke_calls.append(url)
        self.client.calls.append("smoke")
        if self.smoke_error:
            raise self.smoke_error

    def worker_check(self, url: str, deployment_id: str | None, deadline_seconds: float) -> None:
        self.worker_checks.append((url, deployment_id))
        self.client.calls.append(f"worker_check:{deployment_id}")
        if self.worker_check_error:
            raise self.worker_check_error

    def run(self, *argv: str) -> int:
        return main(
            list(argv),
            env=self.env,
            make_client=self.make_client,
            smoke=self.smoke,
            worker_check=self.worker_check,
        )

    def recorded_output(self) -> list[str]:
        return self.github_output.read_text().splitlines() if self.github_output.exists() else []


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


# ---- deploy -----------------------------------------------------------------------------


def test_deploy_moves_web_first_then_the_worker_checking_each_before_the_next(
    harness: Harness,
) -> None:
    code = harness.run("deploy", NEW_IMAGE)

    assert code == 0
    assert harness.client.calls == [
        f"{WEB}:state",
        f"{WORKER}:state",
        f"{WEB}:set_image:{NEW_IMAGE}",
        f"{WEB}:deploy",
        f"wait:dep-{WEB}",
        "smoke",
        f"{WORKER}:set_image:{NEW_IMAGE}",
        f"{WORKER}:deploy",
        f"wait:dep-{WORKER}",
        f"worker_check:dep-{WORKER}",
    ]
    assert harness.smoke_calls == [APP_URL]


def test_the_worker_check_asks_about_the_deployment_that_was_just_started(
    harness: Harness,
) -> None:
    # Not "is any worker alive": the old worker's last heartbeat must not be able to pass this.
    harness.run("deploy", NEW_IMAGE)

    assert harness.worker_checks == [(APP_URL, f"dep-{WORKER}")]


def test_deploy_records_both_previous_images_for_a_later_rollback(harness: Harness) -> None:
    harness.client.images[WORKER] = OLDER_WORKER_IMAGE

    harness.run("deploy", NEW_IMAGE)

    assert f"previous_image={OLD_IMAGE}" in harness.recorded_output()
    assert f"previous_worker_image={OLDER_WORKER_IMAGE}" in harness.recorded_output()


def test_the_previous_images_are_recorded_before_anything_is_changed(harness: Harness) -> None:
    # If the update fails half way, the workflow still needs to know what to restore.
    harness.client.failures[(WEB, "set_image")] = RailwayError("boom")

    code = harness.run("deploy", NEW_IMAGE)

    assert code == 1
    assert f"previous_image={OLD_IMAGE}" in harness.recorded_output()
    assert f"previous_worker_image={OLD_IMAGE}" in harness.recorded_output()


def test_a_first_ever_deploy_records_empty_previous_images(harness: Harness) -> None:
    harness.client.images = {WEB: None, WORKER: None}

    assert harness.run("deploy", NEW_IMAGE) == 0
    assert "previous_image=" in harness.recorded_output()
    assert "previous_worker_image=" in harness.recorded_output()


def test_a_failed_web_deployment_stops_before_the_smoke_test_and_leaves_the_worker_alone(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    harness.client.failures[(WEB, "wait")] = DeploymentFailed(
        "Deployment dep-svc-web ended with status FAILED"
    )

    code = harness.run("deploy", NEW_IMAGE)

    assert code == 1
    assert harness.smoke_calls == []
    assert not any(call.startswith(f"{WORKER}:set_image") for call in harness.client.calls)
    assert "ended with status FAILED" in capsys.readouterr().err


def test_a_failing_smoke_test_leaves_the_worker_alone(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    harness.smoke_error = SmokeTestFailed("after 120s: GET /health returned HTTP 503")

    code = harness.run("deploy", NEW_IMAGE)

    assert code == 1
    assert "GET /health returned HTTP 503" in capsys.readouterr().err
    assert harness.worker_checks == []
    assert not any(call.startswith(f"{WORKER}:set_image") for call in harness.client.calls)


def test_a_worker_that_never_comes_up_fails_the_release(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    harness.worker_check_error = SmokeTestFailed("after 120s: GET /health/worker returned HTTP 503")

    code = harness.run("deploy", NEW_IMAGE)

    assert code == 1
    assert "/health/worker returned HTTP 503" in capsys.readouterr().err


def test_a_worker_deployment_that_crashes_fails_the_release(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    harness.client.failures[(WORKER, "wait")] = DeploymentFailed(
        "Deployment dep-svc-worker ended with status CRASHED"
    )

    code = harness.run("deploy", NEW_IMAGE)

    assert code == 1
    assert harness.worker_checks == []
    assert "ended with status CRASHED" in capsys.readouterr().err


@pytest.mark.parametrize(
    "bad_image",
    [
        "ghcr.io/stefan-dumitru/multi-company-ats:latest",  # moving tag: what runs is unknowable
        "ghcr.io/stefan-dumitru/multi-company-ats",  # no tag at all means :latest
        f"ghcr.io/stefan-dumitru/multi-company-ats:{SHA_NEW}\nmalicious=1",  # output injection
        f"ghcr.io/stefan-dumitru/multi-company-ats:{SHA_NEW} extra",
        f"GHCR.IO/Stefan/ATS:{SHA_NEW}",  # registries and repositories are lowercase
        "",
    ],
)
def test_deploy_refuses_anything_but_an_immutable_image_reference(
    harness: Harness, bad_image: str
) -> None:
    code = harness.run("deploy", bad_image)

    assert code == 2
    assert harness.clients_created == 0  # refused before talking to Railway
    assert harness.recorded_output() == []


def test_deploy_accepts_a_digest_reference(harness: Harness) -> None:
    digest = "sha256:" + "e" * 64

    assert harness.run("deploy", f"ghcr.io/stefan-dumitru/multi-company-ats@{digest}") == 0


def test_missing_settings_are_named_but_secret_values_never_printed(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    del harness.env["RAILWAY_SERVICE_ID"]
    del harness.env["RAILWAY_WORKER_SERVICE_ID"]
    del harness.env["APP_URL"]

    code = harness.run("deploy", NEW_IMAGE)

    output = capsys.readouterr()
    assert code == 2
    for name in ("RAILWAY_SERVICE_ID", "RAILWAY_WORKER_SERVICE_ID", "APP_URL"):
        assert name in output.err
    assert TOKEN not in output.out + output.err


def test_the_token_is_never_printed_on_a_failure(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    harness.client.failures[(WEB, "set_image")] = RailwayError("Not Authorized")

    harness.run("deploy", NEW_IMAGE)

    output = capsys.readouterr()
    assert TOKEN not in output.out + output.err


# ---- rollback ---------------------------------------------------------------------------


def test_rollback_restores_both_services_and_checks_each(harness: Harness) -> None:
    harness.client.images = {WEB: NEW_IMAGE, WORKER: NEW_IMAGE}

    code = harness.run("rollback", OLD_IMAGE, "--worker-image", OLDER_WORKER_IMAGE)

    assert code == 0
    assert harness.client.calls == [
        f"{WEB}:set_image:{OLD_IMAGE}",
        f"{WEB}:deploy",
        f"wait:dep-{WEB}",
        "smoke",
        f"{WORKER}:state",
        f"{WORKER}:set_image:{OLDER_WORKER_IMAGE}",
        f"{WORKER}:deploy",
        f"wait:dep-{WORKER}",
        "worker_check:None",
    ]


def test_rollback_checks_for_any_live_worker_because_an_old_image_may_not_report_its_deployment(
    harness: Harness,
) -> None:
    harness.client.images = {WEB: NEW_IMAGE, WORKER: NEW_IMAGE}

    harness.run("rollback", OLD_IMAGE, "--worker-image", OLDER_WORKER_IMAGE)

    assert harness.worker_checks == [(APP_URL, None)]


def test_rollback_leaves_a_worker_alone_that_never_left_the_old_image(harness: Harness) -> None:
    # The release failed at the web stage, so the worker was never touched: no pointless restart.
    harness.client.images = {WEB: NEW_IMAGE, WORKER: OLD_IMAGE}

    code = harness.run("rollback", OLD_IMAGE, "--worker-image", OLD_IMAGE)

    assert code == 0
    assert not any(call.startswith(f"{WORKER}:set_image") for call in harness.client.calls)
    assert harness.worker_checks == []


def test_rollback_without_a_worker_image_restores_only_the_web_service(harness: Harness) -> None:
    code = harness.run("rollback", OLD_IMAGE)

    assert code == 0
    assert not any(call.startswith(WORKER) for call in harness.client.calls)


def test_rollback_accepts_whatever_tag_was_running_before(harness: Harness) -> None:
    # The previous version may predate the commit-tag rule; it must still be restorable.
    assert harness.run("rollback", "ghcr.io/stefan-dumitru/multi-company-ats:latest") == 0


def test_rollback_refuses_a_worker_image_that_could_smuggle_output_lines(
    harness: Harness,
) -> None:
    code = harness.run("rollback", OLD_IMAGE, "--worker-image", "x\nmalicious=1")

    assert code == 2
    assert harness.clients_created == 0


def test_rollback_without_a_previous_image_explains_there_is_nothing_to_restore(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    code = harness.run("rollback", "")

    assert code == 2
    assert "nothing to roll back" in capsys.readouterr().err.lower()
    assert harness.clients_created == 0


def test_a_failed_rollback_is_reported_as_a_failure(harness: Harness) -> None:
    harness.client.failures[(WEB, "wait")] = DeploymentFailed(
        "Deployment dep-svc-web ended with status CRASHED"
    )

    assert harness.run("rollback", OLD_IMAGE) == 1


def test_a_worker_that_fails_to_roll_back_is_reported_as_a_failure(harness: Harness) -> None:
    harness.client.images = {WEB: NEW_IMAGE, WORKER: NEW_IMAGE}
    harness.client.failures[(WORKER, "wait")] = DeploymentFailed("CRASHED")

    assert harness.run("rollback", OLD_IMAGE, "--worker-image", OLDER_WORKER_IMAGE) == 1
