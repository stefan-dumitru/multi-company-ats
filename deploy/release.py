"""Command line used by the deploy workflow to put a version live, or take it back.

    python -m deploy.release deploy   ghcr.io/<owner>/<repo>:<40-char commit sha>
    python -m deploy.release rollback <image that was running before>

Run from the repository root (the imports need it), hence `-m` rather than a file path.

Settings come from environment variables (set per GitHub environment, so the same workflow code
targets staging or production): RAILWAY_TOKEN, RAILWAY_ENVIRONMENT_ID, RAILWAY_SERVICE_ID, APP_URL.
Exit codes: 0 = done and smoke-tested, 1 = the release failed, 2 = bad input or settings.
"""

import argparse
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from deploy.railway_api import DeploymentFailed, RailwayClient, RailwayError, ServiceState
from deploy.smoke_test import SmokeTestFailed, run_smoke_test

REQUIRED_SETTINGS = ("RAILWAY_TOKEN", "RAILWAY_ENVIRONMENT_ID", "RAILWAY_SERVICE_ID", "APP_URL")

# What may be deployed: a repository pinned by a full commit sha or by a digest. A moving tag
# such as ":latest" is refused, because then the config would not say which code is running.
_IMMUTABLE_IMAGE = re.compile(r"^[a-z0-9][a-z0-9._/-]*(:[0-9a-f]{40}|@sha256:[0-9a-f]{64})$")
# What may be restored: whatever was running before. Still no whitespace, so the value cannot
# smuggle extra lines into the workflow's output file.
_ANY_IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:@-]*$")


class Pipeline(Protocol):
    """The part of RailwayClient the release logic uses (lets tests substitute a fake)."""

    def get_service_state(self, environment_id: str, service_id: str) -> ServiceState: ...
    def set_image(self, environment_id: str, service_id: str, image: str) -> None: ...
    def deploy(self, environment_id: str, service_id: str) -> str: ...
    def wait_for_deployment(self, deployment_id: str, *, timeout: float) -> None: ...


Smoke = Callable[[str, float], None]


@dataclass(frozen=True)
class Config:
    token: str
    environment_id: str
    service_id: str
    app_url: str


class ConfigError(Exception):
    pass


def load_config(env: Mapping[str, str]) -> Config:
    missing = [name for name in REQUIRED_SETTINGS if not env.get(name, "").strip()]
    if missing:
        # Names only: never echo a value, a secret may be among the ones that are present.
        raise ConfigError("Missing settings: " + ", ".join(missing))
    return Config(
        token=env["RAILWAY_TOKEN"],
        environment_id=env["RAILWAY_ENVIRONMENT_ID"],
        service_id=env["RAILWAY_SERVICE_ID"],
        app_url=env["APP_URL"],
    )


def _record_previous_image(env: Mapping[str, str], previous: str | None) -> None:
    """Hand the image that was running to later workflow steps, so a rollback knows its target."""
    print(f"Currently running: {previous or '(nothing deployed yet)'}")
    output_file = env.get("GITHUB_OUTPUT")
    if output_file:
        with Path(output_file).open("a", encoding="utf-8") as handle:
            handle.write(f"previous_image={previous or ''}\n")


def _switch_to(
    client: Pipeline,
    config: Config,
    image: str,
    smoke: Smoke,
    wait_timeout: float,
    smoke_deadline: float,
) -> None:
    client.set_image(config.environment_id, config.service_id, image)
    deployment_id = client.deploy(config.environment_id, config.service_id)
    print(f"Deployment {deployment_id} started for {image}; waiting for Railway to report it live")
    client.wait_for_deployment(deployment_id, timeout=wait_timeout)
    print("Railway reports the deployment is live; running the smoke test")
    smoke(config.app_url, smoke_deadline)
    print(f"Smoke test passed: {image} is live")


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] = os.environ,
    make_client: Callable[[str], Pipeline] = RailwayClient,
    smoke: Smoke = lambda url, deadline: run_smoke_test(url, deadline_seconds=deadline),
) -> int:
    parser = argparse.ArgumentParser(description="Deploy or roll back the ATS on Railway.")
    parser.add_argument("action", choices=["deploy", "rollback"])
    parser.add_argument("image", help="full image reference, e.g. ghcr.io/owner/repo:<commit sha>")
    parser.add_argument(
        "--wait-timeout", type=float, default=600.0, help="seconds to wait for Railway"
    )
    parser.add_argument(
        "--smoke-deadline", type=float, default=120.0, help="seconds for the smoke test"
    )
    args = parser.parse_args(argv)

    if args.action == "rollback" and not args.image:
        print("There is nothing to roll back to: no previous image was recorded.", file=sys.stderr)
        return 2
    allowed = _IMMUTABLE_IMAGE if args.action == "deploy" else _ANY_IMAGE
    if not allowed.fullmatch(args.image):
        kind = "an immutable image (repository:<40-char commit sha> or @sha256:<digest>)"
        print(f"Refusing to {args.action} {args.image!r}: expected {kind}.", file=sys.stderr)
        return 2
    try:
        config = load_config(env)
    except ConfigError as error:
        print(str(error), file=sys.stderr)
        return 2

    client = make_client(config.token)
    try:
        if args.action == "deploy":
            state = client.get_service_state(config.environment_id, config.service_id)
            _record_previous_image(env, state.image)
        _switch_to(client, config, args.image, smoke, args.wait_timeout, args.smoke_deadline)
    except (RailwayError, DeploymentFailed, SmokeTestFailed) as failure:
        print(f"RELEASE FAILED: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
