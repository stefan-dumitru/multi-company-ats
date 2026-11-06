"""Command line used by the deploy workflow to put a version live, or take it back.

    python -m deploy.release deploy   ghcr.io/<owner>/<repo>:<40-char commit sha>
    python -m deploy.release rollback <web image that was running before> \
        [--worker-image <worker image that was running before>]

A release moves the web service first (then smoke-tests it), then the worker to the same image
(then checks that this deployment's worker is alive). Rollback takes both back.

Run from the repository root (the imports need it), hence `-m` rather than a file path.

Settings come from environment variables (set per GitHub environment, so the same workflow code
targets staging or production): RAILWAY_TOKEN, RAILWAY_ENVIRONMENT_ID, RAILWAY_SERVICE_ID (the
web service), RAILWAY_WORKER_SERVICE_ID, APP_URL.
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
from deploy.smoke_test import SmokeTestFailed, run_smoke_test, run_worker_check

REQUIRED_SETTINGS = (
    "RAILWAY_TOKEN",
    "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_SERVICE_ID",
    "RAILWAY_WORKER_SERVICE_ID",
    "APP_URL",
)

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
# (app url, deployment id or None for "any worker", deadline seconds)
WorkerCheck = Callable[[str, str | None, float], None]


@dataclass(frozen=True)
class Config:
    token: str
    environment_id: str
    service_id: str
    worker_service_id: str
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
        worker_service_id=env["RAILWAY_WORKER_SERVICE_ID"],
        app_url=env["APP_URL"],
    )


def _record_previous_images(
    env: Mapping[str, str], web_image: str | None, worker_image: str | None
) -> None:
    """Hand the running images to later workflow steps, so a rollback knows its targets."""
    print(f"Web currently running: {web_image or '(nothing deployed yet)'}")
    print(f"Worker currently running: {worker_image or '(nothing deployed yet)'}")
    output_file = env.get("GITHUB_OUTPUT")
    if output_file:
        with Path(output_file).open("a", encoding="utf-8") as handle:
            handle.write(f"previous_image={web_image or ''}\n")
            handle.write(f"previous_worker_image={worker_image or ''}\n")


def _move_service(
    client: Pipeline, config: Config, service_id: str, image: str, wait_timeout: float
) -> str:
    """Point one service at `image`, deploy it and wait until Railway reports it live.

    Returns the deployment id, which the worker check needs.
    """
    client.set_image(config.environment_id, service_id, image)
    deployment_id = client.deploy(config.environment_id, service_id)
    print(f"Deployment {deployment_id} started for {image}; waiting for Railway to report it live")
    client.wait_for_deployment(deployment_id, timeout=wait_timeout)
    print("Railway reports the deployment is live")
    return deployment_id


def _move_web(
    client: Pipeline, config: Config, image: str, smoke: Smoke, wait_timeout: float, deadline: float
) -> None:
    _move_service(client, config, config.service_id, image, wait_timeout)
    print("Running the smoke test")
    smoke(config.app_url, deadline)
    print(f"Smoke test passed: web is on {image}")


def _move_worker(
    client: Pipeline,
    config: Config,
    image: str,
    worker_check: WorkerCheck,
    wait_timeout: float,
    deadline: float,
    *,
    expect_this_deployment: bool,
) -> None:
    deployment_id = _move_service(client, config, config.worker_service_id, image, wait_timeout)
    print("Checking that the worker is alive")
    # A rollback target may be an old image that does not report its deployment id, so rollbacks
    # settle for "some worker is alive".
    worker_check(config.app_url, deployment_id if expect_this_deployment else None, deadline)
    print(f"Worker check passed: worker is on {image}")


def main(
    argv: Sequence[str] | None = None,
    *,
    env: Mapping[str, str] = os.environ,
    make_client: Callable[[str], Pipeline] = RailwayClient,
    smoke: Smoke = lambda url, deadline: run_smoke_test(url, deadline_seconds=deadline),
    worker_check: WorkerCheck = lambda url, deployment_id, deadline: run_worker_check(
        url, deployment_id, deadline_seconds=deadline
    ),
) -> int:
    parser = argparse.ArgumentParser(description="Deploy or roll back the ATS on Railway.")
    parser.add_argument("action", choices=["deploy", "rollback"])
    parser.add_argument("image", help="full image reference, e.g. ghcr.io/owner/repo:<commit sha>")
    parser.add_argument(
        "--worker-image",
        default="",
        help="rollback only: the image to put back on the worker service (empty: leave it alone)",
    )
    parser.add_argument(
        "--wait-timeout", type=float, default=600.0, help="seconds to wait for Railway"
    )
    parser.add_argument(
        "--smoke-deadline", type=float, default=120.0, help="seconds for each health check"
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
    if args.worker_image and not _ANY_IMAGE.fullmatch(args.worker_image):
        print(f"Refusing to restore the worker image {args.worker_image!r}.", file=sys.stderr)
        return 2
    try:
        config = load_config(env)
    except ConfigError as error:
        print(str(error), file=sys.stderr)
        return 2

    client = make_client(config.token)
    try:
        if args.action == "deploy":
            web = client.get_service_state(config.environment_id, config.service_id)
            worker = client.get_service_state(config.environment_id, config.worker_service_id)
            _record_previous_images(env, web.image, worker.image)
            _move_web(client, config, args.image, smoke, args.wait_timeout, args.smoke_deadline)
            _move_worker(
                client,
                config,
                args.image,
                worker_check,
                args.wait_timeout,
                args.smoke_deadline,
                expect_this_deployment=True,
            )
        else:
            _move_web(client, config, args.image, smoke, args.wait_timeout, args.smoke_deadline)
            if args.worker_image:
                current = client.get_service_state(config.environment_id, config.worker_service_id)
                # Skip a worker that never left the old image (the release failed before it).
                if current.image != args.worker_image:
                    _move_worker(
                        client,
                        config,
                        args.worker_image,
                        worker_check,
                        args.wait_timeout,
                        args.smoke_deadline,
                        expect_this_deployment=False,
                    )
    except (RailwayError, DeploymentFailed, SmokeTestFailed) as failure:
        print(f"RELEASE FAILED: {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
