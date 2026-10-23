"""The Railway client, tested against a fake HTTP layer (no network, no real token)."""

import json
import urllib.error
from typing import Any

import pytest

from deploy.railway_api import (
    DeploymentFailed,
    RailwayClient,
    RailwayError,
    ServiceState,
)

TOKEN = "super-secret-token-value"
ENV_ID = "env-123"
SERVICE_ID = "svc-456"


class FakeRailway:
    """Records every request and replays scripted (status, json-body) answers in order."""

    def __init__(self, *answers: tuple[int, Any] | Exception) -> None:
        self.answers = list(answers)
        self.requests: list[dict[str, Any]] = []

    def __call__(
        self, url: str, headers: dict[str, str], body: bytes, timeout: float
    ) -> tuple[int, bytes]:
        self.requests.append(
            {"url": url, "headers": headers, "body": json.loads(body), "timeout": timeout}
        )
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        status, payload = answer
        return status, payload if isinstance(payload, bytes) else json.dumps(payload).encode()


def client_with(*answers: tuple[int, Any] | Exception) -> tuple[RailwayClient, FakeRailway]:
    fake = FakeRailway(*answers)
    return RailwayClient(TOKEN, post=fake), fake


def ok(data: dict[str, Any]) -> tuple[int, Any]:
    return 200, {"data": data}


def status_answer(status: str) -> tuple[int, Any]:
    return ok({"deployment": {"status": status}})


# ---- requests ---------------------------------------------------------------------------


def test_requests_use_the_project_token_header_and_never_put_the_token_in_the_body() -> None:
    client, fake = client_with(ok({"serviceInstance": {"source": None, "latestDeployment": None}}))

    client.get_service_state(ENV_ID, SERVICE_ID)

    request = fake.requests[0]
    assert request["url"] == "https://backboard.railway.com/graphql/v2"
    assert request["headers"]["Project-Access-Token"] == TOKEN
    assert "Authorization" not in request["headers"]
    assert TOKEN not in json.dumps(request["body"])
    assert request["timeout"] > 0


def test_values_travel_as_graphql_variables_not_pasted_into_the_query() -> None:
    # Building the query by string formatting would let a crafted image name rewrite the query.
    nasty = 'ghcr.io/x/y:abc") { id } #'
    client, fake = client_with(ok({"serviceInstanceUpdate": True}))

    client.set_image(ENV_ID, SERVICE_ID, nasty)

    body = fake.requests[0]["body"]
    assert body["variables"]["image"] == nasty
    assert nasty not in body["query"]


def test_get_service_state_reads_image_and_latest_deployment() -> None:
    client, _ = client_with(
        ok(
            {
                "serviceInstance": {
                    "source": {"image": "ghcr.io/o/r:" + "a" * 40},
                    "latestDeployment": {"id": "dep-1", "status": "SUCCESS"},
                }
            }
        )
    )

    state = client.get_service_state(ENV_ID, SERVICE_ID)

    assert state == ServiceState(
        image="ghcr.io/o/r:" + "a" * 40, latest_deployment_id="dep-1", latest_status="SUCCESS"
    )


def test_get_service_state_copes_with_a_service_that_never_deployed() -> None:
    client, _ = client_with(ok({"serviceInstance": {"source": None, "latestDeployment": None}}))

    state = client.get_service_state(ENV_ID, SERVICE_ID)

    assert state == ServiceState(image=None, latest_deployment_id=None, latest_status=None)


def test_set_image_sends_the_ids_and_the_image() -> None:
    client, fake = client_with(ok({"serviceInstanceUpdate": True}))

    client.set_image(ENV_ID, SERVICE_ID, "ghcr.io/o/r:" + "b" * 40)

    variables = fake.requests[0]["body"]["variables"]
    assert variables == {
        "environmentId": ENV_ID,
        "serviceId": SERVICE_ID,
        "image": "ghcr.io/o/r:" + "b" * 40,
    }


def test_set_image_fails_if_railway_says_it_did_not_apply_it() -> None:
    client, _ = client_with(ok({"serviceInstanceUpdate": False}))

    with pytest.raises(RailwayError, match="image"):
        client.set_image(ENV_ID, SERVICE_ID, "ghcr.io/o/r:" + "b" * 40)


def test_deploy_returns_the_new_deployment_id() -> None:
    client, fake = client_with(ok({"serviceInstanceDeployV2": "dep-99"}))

    assert client.deploy(ENV_ID, SERVICE_ID) == "dep-99"
    assert fake.requests[0]["body"]["variables"] == {
        "environmentId": ENV_ID,
        "serviceId": SERVICE_ID,
    }


# ---- failures ---------------------------------------------------------------------------


def test_graphql_errors_are_raised_with_their_message() -> None:
    client, _ = client_with((200, {"errors": [{"message": "Not Authorized"}]}))

    with pytest.raises(RailwayError, match="Not Authorized"):
        client.get_service_state(ENV_ID, SERVICE_ID)


def test_a_token_echoed_back_in_an_error_is_redacted() -> None:
    client, _ = client_with((200, {"errors": [{"message": f"bad token {TOKEN}"}]}))

    with pytest.raises(RailwayError) as failure:
        client.get_service_state(ENV_ID, SERVICE_ID)

    assert TOKEN not in str(failure.value)


def test_http_errors_report_the_status() -> None:
    client, _ = client_with((401, {"errors": [{"message": "Not Authorized"}]}))

    with pytest.raises(RailwayError, match="401"):
        client.get_service_state(ENV_ID, SERVICE_ID)


def test_network_failures_become_a_railway_error() -> None:
    client, _ = client_with(urllib.error.URLError("connection refused"))

    with pytest.raises(RailwayError, match="reach"):
        client.get_service_state(ENV_ID, SERVICE_ID)


def test_a_response_that_is_not_json_becomes_a_railway_error() -> None:
    client, _ = client_with((200, b"<html>gateway</html>"))

    with pytest.raises(RailwayError, match="JSON"):
        client.get_service_state(ENV_ID, SERVICE_ID)


def test_mutations_are_never_retried() -> None:
    # A retried "deploy" could start two deployments; the one failure must reach the caller.
    client, fake = client_with(urllib.error.URLError("reset"), ok({"serviceInstanceDeployV2": "x"}))

    with pytest.raises(RailwayError):
        client.deploy(ENV_ID, SERVICE_ID)

    assert len(fake.requests) == 1


# ---- waiting for a deployment -----------------------------------------------------------


class FakeTime:
    """Replaces sleeping and the clock so timeout logic runs instantly and deterministically."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def clock(self) -> float:
        return self.now


def wait(client: RailwayClient, fake_time: FakeTime, timeout: float = 100.0) -> None:
    client.wait_for_deployment(
        "dep-1", timeout=timeout, interval=5.0, sleep=fake_time.sleep, clock=fake_time.clock
    )


def test_wait_returns_once_the_deployment_succeeds() -> None:
    fake_time = FakeTime()
    client, fake = client_with(
        status_answer("BUILDING"), status_answer("DEPLOYING"), status_answer("SUCCESS")
    )

    wait(client, fake_time)

    assert len(fake.requests) == 3
    assert fake_time.sleeps == [5.0, 5.0]


@pytest.mark.parametrize("final_status", ["FAILED", "CRASHED", "REMOVED", "SKIPPED"])
def test_wait_raises_when_the_deployment_ends_badly(final_status: str) -> None:
    client, _ = client_with(status_answer("DEPLOYING"), status_answer(final_status))

    with pytest.raises(DeploymentFailed, match=final_status):
        wait(client, FakeTime())


def test_wait_gives_up_at_the_timeout_and_reports_the_last_status() -> None:
    fake_time = FakeTime()
    client, _ = client_with(*[status_answer("DEPLOYING")] * 50)

    with pytest.raises(DeploymentFailed, match=r"within 20s.*DEPLOYING"):
        wait(client, fake_time, timeout=20.0)

    assert fake_time.now <= 25.0  # stopped promptly instead of polling forever


def test_wait_survives_a_brief_api_outage() -> None:
    # Polling is read-only, so a blip must not fail a deployment that is actually fine.
    client, _ = client_with(
        status_answer("DEPLOYING"), urllib.error.URLError("blip"), status_answer("SUCCESS")
    )

    wait(client, FakeTime())


def test_wait_fails_if_the_api_stays_down_until_the_timeout() -> None:
    client, _ = client_with(*[urllib.error.URLError("down")] * 50)

    with pytest.raises(DeploymentFailed, match="reach"):
        wait(client, FakeTime(), timeout=20.0)
