"""The release command: the order of steps, the safety checks, and what it refuses to do."""

from pathlib import Path

import pytest

from deploy.railway_api import DeploymentFailed, RailwayError, ServiceState
from deploy.release import main

SHA_NEW = "c" * 40
SHA_OLD = "d" * 40
NEW_IMAGE = f"ghcr.io/stefan-dumitru/multi-company-ats:{SHA_NEW}"
OLD_IMAGE = f"ghcr.io/stefan-dumitru/multi-company-ats:{SHA_OLD}"
TOKEN = "super-secret-token-value"


class FakeClient:
    def __init__(self, current_image: str | None = OLD_IMAGE) -> None:
        self.calls: list[str] = []
        self.current_image = current_image
        self.set_image_error: Exception | None = None
        self.wait_error: Exception | None = None

    def get_service_state(self, environment_id: str, service_id: str) -> ServiceState:
        self.calls.append("get_service_state")
        return ServiceState(self.current_image, "dep-0", "SUCCESS")

    def set_image(self, environment_id: str, service_id: str, image: str) -> None:
        self.calls.append(f"set_image:{image}")
        if self.set_image_error:
            raise self.set_image_error

    def deploy(self, environment_id: str, service_id: str) -> str:
        self.calls.append("deploy")
        return "dep-1"

    def wait_for_deployment(self, deployment_id: str, *, timeout: float) -> None:
        self.calls.append(f"wait:{deployment_id}")
        if self.wait_error:
            raise self.wait_error


class Harness:
    """Runs main() with a fake Railway client and a fake smoke test, and collects the effects."""

    def __init__(self, tmp_path: Path) -> None:
        self.client = FakeClient()
        self.smoke_calls: list[str] = []
        self.smoke_error: Exception | None = None
        self.github_output = tmp_path / "github_output.txt"
        self.env = {
            "RAILWAY_TOKEN": TOKEN,
            "RAILWAY_ENVIRONMENT_ID": "env-1",
            "RAILWAY_SERVICE_ID": "svc-1",
            "APP_URL": "https://ats-staging.example.com",
            "GITHUB_OUTPUT": str(self.github_output),
        }
        self.clients_created = 0

    def make_client(self, token: str) -> FakeClient:
        self.clients_created += 1
        return self.client

    def smoke(self, url: str, deadline_seconds: float) -> None:
        self.smoke_calls.append(url)
        if self.smoke_error:
            raise self.smoke_error

    def run(self, *argv: str) -> int:
        return main(list(argv), env=self.env, make_client=self.make_client, smoke=self.smoke)

    def recorded_output(self) -> str:
        return self.github_output.read_text() if self.github_output.exists() else ""


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


# ---- deploy -----------------------------------------------------------------------------


def test_deploy_runs_the_steps_in_order_and_smoke_tests_the_app_url(harness: Harness) -> None:
    code = harness.run("deploy", NEW_IMAGE)

    assert code == 0
    assert harness.client.calls == [
        "get_service_state",
        f"set_image:{NEW_IMAGE}",
        "deploy",
        "wait:dep-1",
    ]
    assert harness.smoke_calls == ["https://ats-staging.example.com"]


def test_deploy_records_the_previous_image_for_a_later_rollback(harness: Harness) -> None:
    harness.run("deploy", NEW_IMAGE)

    assert f"previous_image={OLD_IMAGE}" in harness.recorded_output().splitlines()


def test_the_previous_image_is_recorded_before_anything_is_changed(harness: Harness) -> None:
    # If the update fails half way, the workflow still needs to know what to restore.
    harness.client.set_image_error = RailwayError("boom")

    code = harness.run("deploy", NEW_IMAGE)

    assert code == 1
    assert f"previous_image={OLD_IMAGE}" in harness.recorded_output().splitlines()


def test_a_first_ever_deploy_records_an_empty_previous_image(harness: Harness) -> None:
    harness.client.current_image = None

    assert harness.run("deploy", NEW_IMAGE) == 0
    assert "previous_image=" in harness.recorded_output().splitlines()


def test_a_failed_deployment_stops_before_the_smoke_test(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    harness.client.wait_error = DeploymentFailed("Deployment dep-1 ended with status FAILED")

    code = harness.run("deploy", NEW_IMAGE)

    assert code == 1
    assert harness.smoke_calls == []
    assert "ended with status FAILED" in capsys.readouterr().err


def test_a_failing_smoke_test_fails_the_release(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    from deploy.smoke_test import SmokeTestFailed

    harness.smoke_error = SmokeTestFailed("after 120s: GET /health returned HTTP 503")

    code = harness.run("deploy", NEW_IMAGE)

    assert code == 1
    assert "GET /health returned HTTP 503" in capsys.readouterr().err


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
    assert harness.recorded_output() == ""


def test_deploy_accepts_a_digest_reference(harness: Harness) -> None:
    digest = "sha256:" + "e" * 64

    assert harness.run("deploy", f"ghcr.io/stefan-dumitru/multi-company-ats@{digest}") == 0


def test_missing_settings_are_named_but_secret_values_never_printed(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    del harness.env["RAILWAY_SERVICE_ID"]
    del harness.env["APP_URL"]

    code = harness.run("deploy", NEW_IMAGE)

    output = capsys.readouterr()
    assert code == 2
    assert "RAILWAY_SERVICE_ID" in output.err and "APP_URL" in output.err
    assert TOKEN not in output.out + output.err


def test_the_token_is_never_printed_on_a_failure(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    harness.client.set_image_error = RailwayError("Not Authorized")

    harness.run("deploy", NEW_IMAGE)

    output = capsys.readouterr()
    assert TOKEN not in output.out + output.err


# ---- rollback ---------------------------------------------------------------------------


def test_rollback_restores_the_given_image_and_smoke_tests_it(harness: Harness) -> None:
    code = harness.run("rollback", OLD_IMAGE)

    assert code == 0
    assert harness.client.calls == [f"set_image:{OLD_IMAGE}", "deploy", "wait:dep-1"]
    assert harness.smoke_calls == ["https://ats-staging.example.com"]


def test_rollback_accepts_whatever_tag_was_running_before(harness: Harness) -> None:
    # The previous version may predate the commit-tag rule; it must still be restorable.
    assert harness.run("rollback", "ghcr.io/stefan-dumitru/multi-company-ats:latest") == 0


def test_rollback_without_a_previous_image_explains_there_is_nothing_to_restore(
    harness: Harness, capsys: pytest.CaptureFixture[str]
) -> None:
    code = harness.run("rollback", "")

    assert code == 2
    assert "nothing to roll back" in capsys.readouterr().err.lower()
    assert harness.clients_created == 0


def test_a_failed_rollback_is_reported_as_a_failure(harness: Harness) -> None:
    harness.client.wait_error = DeploymentFailed("Deployment dep-1 ended with status CRASHED")

    assert harness.run("rollback", OLD_IMAGE) == 1
