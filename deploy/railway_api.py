"""A small client for the parts of Railway's GraphQL API the deploy pipeline needs.

Field and mutation names come from Railway's public schema (https://backboard.railway.com/graphql/v2).
Standard library only. The HTTP call is injectable, so tests never touch the network.
"""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

ENDPOINT = "https://backboard.railway.com/graphql/v2"

# (url, headers, body, timeout) -> (HTTP status, response body)
Post = Callable[[str, dict[str, str], bytes, float], tuple[int, bytes]]

# A deployment in any of these states will never become the live version.
_ENDED_BADLY = {"FAILED", "CRASHED", "REMOVED", "REMOVING", "SKIPPED", "NEEDS_APPROVAL"}


class RailwayError(Exception):
    """A call to the Railway API failed."""


class DeploymentFailed(Exception):
    """A deployment ended badly, or did not finish in time."""


@dataclass(frozen=True)
class ServiceState:
    image: str | None
    latest_deployment_id: str | None
    latest_status: str | None


def _urllib_post(
    url: str, headers: dict[str, str], body: bytes, timeout: float
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


class RailwayClient:
    def __init__(
        self,
        token: str,
        *,
        post: Post = _urllib_post,
        endpoint: str = ENDPOINT,
        request_timeout: float = 30.0,
        token_header: str = "Project-Access-Token",
    ) -> None:
        self._token = token
        self._post = post
        self._endpoint = endpoint
        self._request_timeout = request_timeout
        self._token_header = token_header

    def _redact(self, text: str) -> str:
        return text.replace(self._token, "[redacted]") if self._token else text

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "ats-deploy",
            self._token_header: self._token,
        }
        # Values go in "variables", never into the query text, so they cannot alter the query.
        body = json.dumps({"query": query, "variables": variables}).encode()
        try:
            status, raw = self._post(self._endpoint, headers, body, self._request_timeout)
        except (OSError, urllib.error.URLError) as error:
            # Only the exception type is reported: its text could contain request details.
            raise RailwayError(
                f"Could not reach the Railway API ({type(error).__name__})"
            ) from None

        try:
            payload = json.loads(raw)
        except ValueError:
            raise RailwayError(
                f"Railway API returned HTTP {status} and a body that is not JSON"
            ) from None

        errors = payload.get("errors") if isinstance(payload, dict) else None
        if errors:
            messages = "; ".join(str(e.get("message", "unknown error")) for e in errors)
            raise RailwayError(f"Railway API error (HTTP {status}): {self._redact(messages)}")
        if status != 200:
            raise RailwayError(f"Railway API returned HTTP {status}")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise RailwayError("Railway API answer had no data")
        return data

    def get_service_state(self, environment_id: str, service_id: str) -> ServiceState:
        data = self._graphql(
            "query($environmentId: String!, $serviceId: String!) {"
            " serviceInstance(environmentId: $environmentId, serviceId: $serviceId) {"
            " source { image } latestDeployment { id status } } }",
            {"environmentId": environment_id, "serviceId": service_id},
        )
        instance = data["serviceInstance"]
        source = instance.get("source") or {}
        latest = instance.get("latestDeployment") or {}
        return ServiceState(
            image=source.get("image"),
            latest_deployment_id=latest.get("id"),
            latest_status=latest.get("status"),
        )

    def set_image(self, environment_id: str, service_id: str, image: str) -> None:
        data = self._graphql(
            "mutation($environmentId: String!, $serviceId: String!, $image: String!) {"
            " serviceInstanceUpdate(environmentId: $environmentId, serviceId: $serviceId,"
            " input: { source: { image: $image } }) }",
            {"environmentId": environment_id, "serviceId": service_id, "image": image},
        )
        if data.get("serviceInstanceUpdate") is not True:
            raise RailwayError("Railway did not apply the new image")

    def deploy(self, environment_id: str, service_id: str) -> str:
        """Start a deployment of the service's current image and return its deployment id.

        Never retried: a second attempt could start a second deployment.
        """
        data = self._graphql(
            "mutation($environmentId: String!, $serviceId: String!) {"
            " serviceInstanceDeployV2(environmentId: $environmentId, serviceId: $serviceId) }",
            {"environmentId": environment_id, "serviceId": service_id},
        )
        return str(data["serviceInstanceDeployV2"])

    def get_deployment_status(self, deployment_id: str) -> str:
        data = self._graphql(
            "query($id: String!) { deployment(id: $id) { status } }", {"id": deployment_id}
        )
        return str(data["deployment"]["status"])

    def wait_for_deployment(
        self,
        deployment_id: str,
        *,
        timeout: float = 600.0,
        interval: float = 5.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Block until Railway reports the deployment SUCCESS; raise DeploymentFailed otherwise.

        SUCCESS means Railway's own health check passed and traffic moved to the new version, so a
        smoke test run afterwards cannot be answered by the old version.
        """
        deadline = clock() + timeout
        last = "no answer yet"
        while True:
            status: str | None
            try:
                status = self.get_deployment_status(deployment_id)
                last = f"last status: {status}"
            except RailwayError as error:
                # Polling only reads, so a brief API outage is retried until the deadline.
                status = None
                last = f"last error: {error}"
            if status == "SUCCESS":
                return
            if status in _ENDED_BADLY:
                raise DeploymentFailed(f"Deployment {deployment_id} ended with status {status}")
            if clock() + interval > deadline:
                raise DeploymentFailed(
                    f"Deployment {deployment_id} did not succeed within {timeout:g}s ({last})"
                )
            sleep(interval)
