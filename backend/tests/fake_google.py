"""A fake Google, so no test ever reaches the real one.

It plugs in where `app.integrations.google` makes its one outgoing call (`google.transport`), and
it answers what Google is asked: the token endpoint (exchange a code, refresh an access token),
revocation, and the primary calendar's events (create, change, delete). It checks what it is sent
the way Google would (the client's id and secret, the redirect address, a known code or refresh
token, a valid access token, an event id that is not taken), records every call, and can be told to
fail the next one.
"""

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from app.integrations import google


@dataclass
class Call:
    method: str
    url: str
    headers: dict[str, str]
    form: dict[str, str]
    timeout: float
    body: dict[str, Any] | None = None  # the JSON a calendar call carried
    query: dict[str, str] = field(default_factory=dict)


@dataclass
class Failure:
    status: int = 500
    body: bytes = b"{}"
    raises: Exception | None = None


@dataclass
class FakeGoogle:
    client_id: str
    client_secret: str
    redirect_uri: str
    calls: list[Call] = field(default_factory=list)
    # code -> what Google gives back for it
    codes: dict[str, dict[str, str]] = field(default_factory=dict)
    refresh_tokens: set[str] = field(default_factory=set)
    revoked: list[str] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)
    # event id -> the event as Google would hold it (what the last create or change sent)
    events: dict[str, dict[str, Any]] = field(default_factory=dict)

    def grant_code(
        self,
        code: str,
        *,
        refresh_token: str | None = "refresh-token-1",
        access_token: str = "access-token-1",
        scope: str = google.SCOPE,
    ) -> None:
        """Make this code exchangeable, as if the person had just agreed in Google's window."""
        answer = {"access_token": access_token, "scope": scope, "expires_in": "3599"}
        if refresh_token is not None:
            answer["refresh_token"] = refresh_token
            self.refresh_tokens.add(refresh_token)
        self.codes[code] = answer

    def fail_next(
        self, status: int = 500, body: bytes = b"{}", raises: Exception | None = None
    ) -> None:
        self.failures.append(Failure(status, body, raises))

    def calls_to(self, url: str) -> list[Call]:
        return [call for call in self.calls if call.url == url]

    def transport(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float
    ) -> tuple[int, bytes]:
        parts = urlsplit(url)
        query = {key: values[0] for key, values in parse_qs(parts.query).items()}
        is_calendar = url.startswith(google.EVENTS_URL)
        form: dict[str, str] = {}
        json_body: dict[str, Any] | None = None
        if is_calendar:
            json_body = json.loads(body) if body else None
        else:
            form = {key: values[0] for key, values in parse_qs((body or b"").decode()).items()}
        self.calls.append(Call(method, url, dict(headers), form, timeout, json_body, query))
        if self.failures:
            failure = self.failures.pop(0)
            if failure.raises is not None:
                raise failure.raises
            return failure.status, failure.body

        path = parts._replace(query="", fragment="").geturl()
        if is_calendar:
            return self._events(method, path, headers, json_body)
        if path == google.TOKEN_URL:
            return self._token(form)
        if path == google.REVOKE_URL:
            self.revoked.append(form.get("token", ""))
            return 200, b"{}"
        return 404, json.dumps({"error": "not_found"}).encode()

    def calendar_calls(self) -> list[Call]:
        return [call for call in self.calls if call.url.startswith(google.EVENTS_URL)]

    def _events(
        self, method: str, path: str, headers: dict[str, str], body: dict[str, Any] | None
    ) -> tuple[int, bytes]:
        if headers.get("Authorization") != "Bearer fresh-access-token":
            return 401, json.dumps({"error": {"code": 401}}).encode()
        event_id = unquote(path[len(google.EVENTS_URL) :].lstrip("/"))
        if method == "POST":
            assert body is not None
            if body["id"] in self.events:
                return 409, json.dumps({"error": {"code": 409}}).encode()
            self.events[body["id"]] = body
            return 200, b"{}"
        if event_id not in self.events:
            return 404, json.dumps({"error": {"code": 404}}).encode()
        if method == "PATCH":
            assert body is not None
            self.events[event_id] = {**self.events[event_id], **body}
            return 200, b"{}"
        if method == "DELETE":
            del self.events[event_id]
            return 204, b""
        return 405, b"{}"

    def _token(self, form: dict[str, str]) -> tuple[int, bytes]:
        if (
            form.get("client_id") != self.client_id
            or form.get("client_secret") != self.client_secret
        ):
            return 401, json.dumps({"error": "invalid_client"}).encode()
        if form.get("grant_type") == "authorization_code":
            answer = self.codes.pop(form.get("code", ""), None)  # a code works once
            if answer is None or form.get("redirect_uri") != self.redirect_uri:
                return 400, json.dumps({"error": "invalid_grant"}).encode()
            return 200, json.dumps(answer).encode()
        if form.get("grant_type") == "refresh_token":
            if form.get("refresh_token") not in self.refresh_tokens:
                return 400, json.dumps({"error": "invalid_grant"}).encode()
            return (
                200,
                json.dumps({"access_token": "fresh-access-token", "expires_in": 3599}).encode(),
            )
        return 400, json.dumps({"error": "unsupported_grant_type"}).encode()
