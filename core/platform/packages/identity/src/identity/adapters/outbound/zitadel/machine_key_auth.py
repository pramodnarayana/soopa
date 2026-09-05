import asyncio
import json
import time
from collections.abc import Mapping
from dataclasses import dataclass

import httpx
import jwt


class ZitadelMachineAuthenticationError(RuntimeError):
    """Raised when a Zitadel machine key cannot produce an access token."""


@dataclass(frozen=True)
class ZitadelMachineKey:
    key_id: str
    private_key: str
    user_id: str

    @classmethod
    def from_json(cls, value: str) -> "ZitadelMachineKey":
        try:
            raw: object = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ZitadelMachineAuthenticationError(
                "ZITADEL_MACHINE_KEY must be valid JSON"
            ) from exc

        if not isinstance(raw, dict):
            raise ZitadelMachineAuthenticationError(
                "ZITADEL_MACHINE_KEY must contain a JSON object"
            )

        details: Mapping[object, object] = raw
        return cls(
            key_id=_required_string(details, "keyId"),
            private_key=_required_string(details, "key"),
            user_id=_required_string(details, "userId"),
        )


def _required_string(details: Mapping[object, object], field: str) -> str:
    value = details.get(field)
    if not isinstance(value, str) or not value:
        raise ZitadelMachineAuthenticationError(
            f"ZITADEL_MACHINE_KEY is missing required field {field}"
        )
    return value


class ZitadelMachineTokenProvider:
    """Exchange a machine key for short-lived Zitadel API access tokens."""

    _ASSERTION_LIFETIME_SECONDS = 300
    _TOKEN_REFRESH_SKEW_SECONDS = 30
    _API_SCOPE = "openid urn:zitadel:iam:org:project:id:zitadel:aud"
    _JWT_BEARER_GRANT = "urn:ietf:params:oauth:grant-type:jwt-bearer"

    def __init__(self, api_url: str, machine_key: str) -> None:
        self._api_url = api_url.rstrip("/")
        if not self._api_url:
            raise ZitadelMachineAuthenticationError("ZITADEL_API_URL is required")
        self._machine_key = ZitadelMachineKey.from_json(machine_key)
        self._cached_token: str | None = None
        self._refresh_at = 0.0
        self._lock = asyncio.Lock()

    async def get_access_token(self, client: httpx.AsyncClient) -> str:
        if self._cached_token is not None and time.monotonic() < self._refresh_at:
            return self._cached_token

        async with self._lock:
            if self._cached_token is not None and time.monotonic() < self._refresh_at:
                return self._cached_token

            token, expires_in = await self._exchange(client)
            self._cached_token = token
            self._refresh_at = time.monotonic() + max(
                expires_in - self._TOKEN_REFRESH_SKEW_SECONDS,
                0,
            )
            return token

    async def _exchange(self, client: httpx.AsyncClient) -> tuple[str, int]:
        issued_at = int(time.time())
        try:
            assertion = jwt.encode(
                {
                    "iss": self._machine_key.user_id,
                    "sub": self._machine_key.user_id,
                    "aud": self._api_url,
                    "iat": issued_at,
                    "exp": issued_at + self._ASSERTION_LIFETIME_SECONDS,
                },
                self._machine_key.private_key,
                algorithm="RS256",
                headers={"kid": self._machine_key.key_id},
            )
        except (jwt.PyJWTError, TypeError, ValueError) as exc:
            raise ZitadelMachineAuthenticationError(
                "ZITADEL_MACHINE_KEY could not sign an authentication assertion"
            ) from exc

        try:
            response = await client.post(
                f"{self._api_url}/oauth/v2/token",
                data={
                    "grant_type": self._JWT_BEARER_GRANT,
                    "scope": self._API_SCOPE,
                    "assertion": assertion,
                },
            )
        except httpx.HTTPError as exc:
            raise ZitadelMachineAuthenticationError(
                "Zitadel machine authentication request failed"
            ) from exc
        if response.is_error:
            raise ZitadelMachineAuthenticationError(
                f"Zitadel machine authentication failed with status {response.status_code}"
            )

        try:
            payload: object = response.json()
        except ValueError as exc:
            raise ZitadelMachineAuthenticationError(
                "Zitadel token endpoint returned invalid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ZitadelMachineAuthenticationError(
                "Zitadel token endpoint returned an invalid response"
            )
        token_response: Mapping[object, object] = payload
        access_token = token_response.get("access_token")
        expires_in = token_response.get("expires_in")
        if not isinstance(access_token, str) or not access_token:
            raise ZitadelMachineAuthenticationError(
                "Zitadel token endpoint did not return an access token"
            )
        if isinstance(expires_in, bool) or not isinstance(expires_in, int):
            raise ZitadelMachineAuthenticationError(
                "Zitadel token endpoint did not return a valid expiry"
            )
        return access_token, expires_in
