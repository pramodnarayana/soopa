"""Pure behavioral unit tests for the cloud Casdoor bootstrapper (zero mocks)."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import botocore.exceptions

CASDOOR_STACK_DIR = str(Path(__file__).resolve().parents[1] / "casdoor")
if CASDOOR_STACK_DIR not in sys.path:
    sys.path.insert(0, CASDOOR_STACK_DIR)

from bootstrap import (
    AwsSecretsManagerAdapter,
    BootstrapResult,
    CasdoorBootstrapConfig,
    CasdoorCloudBootstrapper,
    HttpResponsePort,
    resolve_bootstrap_config,
)
from constants import (
    CasdoorAdminOAuthSecretKey,
    CasdoorApplicationName,
    CasdoorBootstrapEndpoint,
    CasdoorBootstrapErrorCode,
    CasdoorConstants,
    CasdoorGrantType,
    CasdoorRealm,
    CasdoorTokenFormat,
)


@dataclass(frozen=True)
class _FakeResponse:
    status_code: int
    payload: object
    text: str = ""
    raise_json_error: bool = False

    def json(self) -> object:
        if self.raise_json_error:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self.payload


class _InMemorySecretsStore:
    """Pure in-memory implementation of SecretsStorePort."""

    def __init__(self, initial: dict[str, str] | None = None) -> None:
        self.values: dict[str, str] = dict(initial or {})
        self.put_calls: list[tuple[str, str]] = []

    def get_secret_string(self, secret_arn: str) -> BootstrapResult[str | None]:
        return BootstrapResult.ok(self.values.get(secret_arn))

    def put_secret_string(self, secret_arn: str, secret_string: str) -> BootstrapResult[None]:
        self.values[secret_arn] = secret_string
        self.put_calls.append((secret_arn, secret_string))
        return BootstrapResult.ok(None)


class _FakeBotoSecretsClient:
    """Pure in-memory stub exercising AwsSecretsManagerAdapter error mapping."""

    def __init__(self, *, error_code: str | None = None, secret_string: str | None = None) -> None:
        self._error_code = error_code
        self._secret_string = secret_string

    def get_secret_value(self, *, SecretId: str) -> Mapping[str, object]:
        del SecretId
        if self._error_code is not None:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": self._error_code, "Message": "simulated error"}},
                "GetSecretValue",
            )
        if self._secret_string is None:
            return {}
        return {"SecretString": self._secret_string}

    def put_secret_value(self, *, SecretId: str, SecretString: str) -> Mapping[str, object]:
        del SecretId, SecretString
        if self._error_code is not None:
            raise botocore.exceptions.ClientError(
                {"Error": {"Code": self._error_code, "Message": "simulated error"}},
                "PutSecretValue",
            )
        return {}


class _InMemoryCasdoorServer:
    """Stateful in-memory Casdoor HTTP server simulating cookies, password rotation, and CRUD."""

    def __init__(
        self,
        *,
        admin_password: str = CasdoorConstants.FACTORY_DEFAULT_ADMIN_PASSWORD,
        unhealthy_probes: int = 0,
        mask_m2m_secret: bool = False,
        fail_set_password: bool = False,
        return_html_on_login: bool = False,
    ) -> None:
        self.admin_password = admin_password
        self.unhealthy_probes = unhealthy_probes
        self.mask_m2m_secret = mask_m2m_secret
        self.fail_set_password = fail_set_password
        self.return_html_on_login = return_html_on_login
        self.authenticated = False
        self.orgs: dict[str, dict[str, object]] = {}
        self.apps: dict[str, dict[str, object]] = {}
        self.users: dict[str, dict[str, object]] = {}
        self.requests: list[tuple[str, str]] = []
        self._user_counter = 100

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, str] | None = None,
        json: Mapping[str, object] | None = None,
        data: Mapping[str, str] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> BootstrapResult[HttpResponsePort]:
        path = "/" + url.split("://", 1)[1].split("/", 1)[1]
        self.requests.append((method, path))
        query = dict(params or {})
        body = dict(json or {})
        form_data = dict(data or {})
        req_headers = dict(headers or {})

        if path == CasdoorBootstrapEndpoint.HEALTH.value:
            return BootstrapResult.ok(self._handle_health())
        if path == CasdoorBootstrapEndpoint.LOGIN.value:
            return BootstrapResult.ok(self._handle_login(body))
        if not self.authenticated:
            return BootstrapResult.ok(
                _FakeResponse(200, {"status": "error", "msg": "please sign in first"})
            )
        if path == CasdoorBootstrapEndpoint.SET_PASSWORD.value:
            return BootstrapResult.ok(self._handle_set_password(form_data, body, req_headers))

        handlers = {
            CasdoorBootstrapEndpoint.GET_ORGANIZATION.value: self._handle_get_org,
            CasdoorBootstrapEndpoint.ADD_ORGANIZATION.value: self._handle_add_org,
            CasdoorBootstrapEndpoint.UPDATE_ORGANIZATION.value: self._handle_update_org,
            CasdoorBootstrapEndpoint.GET_APPLICATION.value: self._handle_get_app,
            CasdoorBootstrapEndpoint.ADD_APPLICATION.value: self._handle_add_app,
            CasdoorBootstrapEndpoint.UPDATE_APPLICATION.value: self._handle_update_app,
            CasdoorBootstrapEndpoint.GET_USER.value: self._handle_get_user,
            CasdoorBootstrapEndpoint.ADD_USER.value: self._handle_add_user,
        }
        handler = handlers.get(path)
        if handler is None:
            return BootstrapResult.ok(_FakeResponse(404, {"status": "error", "msg": "not found"}))
        return BootstrapResult.ok(handler(query, body))

    def _handle_health(self) -> _FakeResponse:
        if self.unhealthy_probes > 0:
            self.unhealthy_probes -= 1
            return _FakeResponse(503, {"status": "error"})
        return _FakeResponse(200, {"status": "ok"})

    def _handle_login(self, body: dict[str, object]) -> _FakeResponse:
        if self.return_html_on_login:
            return _FakeResponse(
                200, None, text="<html>Gateway Error</html>", raise_json_error=True
            )
        if (
            body.get("organization") == CasdoorRealm.BUILT_IN.value
            and body.get("username") == CasdoorConstants.BUILT_IN_ADMIN_USER
            and body.get("password") == self.admin_password
        ):
            self.authenticated = True
            return _FakeResponse(200, {"status": "ok", "data": "admin"})
        return _FakeResponse(200, {"status": "error", "msg": "invalid password"})

    def _handle_set_password(
        self,
        form_data: dict[str, str],
        json_body: dict[str, object],
        headers: dict[str, str],
    ) -> _FakeResponse:
        # Mirror Casdoor v4.30+ SetPassword(): reads `c.Ctx.Request.Form.Get(...)` (form-encoded only).
        if json_body or not form_data:
            return _FakeResponse(200, {"status": "error", "msg": "The user: / doesn't exist"})
        if headers.get("Content-Type") != "application/x-www-form-urlencoded":
            return _FakeResponse(200, {"status": "error", "msg": "invalid content-type"})
        if self.fail_set_password:
            return _FakeResponse(200, {"status": "error", "msg": "rotation rejected"})
        if form_data.get("oldPassword") != self.admin_password:
            return _FakeResponse(200, {"status": "error", "msg": "old password mismatch"})
        self.admin_password = form_data["newPassword"]
        # Mirror Casdoor security behavior: password change invalidates active sessions.
        self.authenticated = False
        return _FakeResponse(200, {"status": "ok"})

    def _handle_get_org(self, query: dict[str, str], _body: dict[str, object]) -> _FakeResponse:
        return _FakeResponse(200, {"status": "ok", "data": self.orgs.get(query["id"])})

    def _handle_add_org(self, _query: dict[str, str], body: dict[str, object]) -> _FakeResponse:
        self.orgs[f"{body['owner']}/{body['name']}"] = dict(body)
        return _FakeResponse(200, {"status": "ok"})

    def _handle_update_org(self, query: dict[str, str], body: dict[str, object]) -> _FakeResponse:
        self.orgs[query["id"]] = dict(body)
        return _FakeResponse(200, {"status": "ok"})

    def _handle_get_app(self, query: dict[str, str], _body: dict[str, object]) -> _FakeResponse:
        app_doc = self.apps.get(query["id"])
        if app_doc is not None and self.mask_m2m_secret and query["id"].endswith("api-m2m"):
            masked = dict(app_doc)
            masked["clientSecret"] = CasdoorConstants.MASKED_SECRET_SENTINEL
            return _FakeResponse(200, {"status": "ok", "data": masked})
        return _FakeResponse(200, {"status": "ok", "data": app_doc})

    def _handle_add_app(self, _query: dict[str, str], body: dict[str, object]) -> _FakeResponse:
        self.apps[f"{body['owner']}/{body['name']}"] = dict(body)
        return _FakeResponse(200, {"status": "ok"})

    def _handle_update_app(self, query: dict[str, str], body: dict[str, object]) -> _FakeResponse:
        self.apps[query["id"]] = dict(body)
        return _FakeResponse(200, {"status": "ok"})

    def _handle_get_user(self, query: dict[str, str], _body: dict[str, object]) -> _FakeResponse:
        return _FakeResponse(200, {"status": "ok", "data": self.users.get(query["id"])})

    def _handle_add_user(self, _query: dict[str, str], body: dict[str, object]) -> _FakeResponse:
        self._user_counter += 1
        stored = dict(body)
        stored["id"] = f"usr-casdoor-{self._user_counter}"
        self.users[f"{body['owner']}/{body['name']}"] = stored
        return _FakeResponse(200, {"status": "ok"})


_ADMIN_PWD_ARN = "arn:aws:secretsmanager:us-east-1:123:secret:admin-pwd"
_PLATFORM_ADMIN_PWD_ARN = "arn:aws:secretsmanager:us-east-1:123:secret:platform-admin-pwd"
_ADMIN_OAUTH_ARN = "arn:aws:secretsmanager:us-east-1:123:secret:admin-oauth"


def _make_config(
    *,
    identity_base_url: str = "https://identity.staging.flowwolf.io",
    dashboard_base_url: str = "https://dashboard.staging.flowwolf.io",
    platform_realm: str = CasdoorRealm.PLATFORM.value,
    global_realm: str = CasdoorRealm.GLOBAL.value,
) -> CasdoorBootstrapConfig:
    return CasdoorBootstrapConfig(
        identity_base_url=identity_base_url,
        dashboard_base_url=dashboard_base_url,
        platform_realm=platform_realm,
        global_realm=global_realm,
        admin_password_secret_arn=_ADMIN_PWD_ARN,
        platform_admin_password_secret_arn=_PLATFORM_ADMIN_PWD_ARN,
        admin_oauth_secret_arn=_ADMIN_OAUTH_ARN,
        platform_admin_email="admin@flowwolf.io",
        health_timeout_seconds=10,
        health_poll_interval_seconds=1.0,
    )


def _make_secrets_store(extra: dict[str, str] | None = None) -> _InMemorySecretsStore:
    initial = {
        _ADMIN_PWD_ARN: "StrongManagedPass!99",
        _PLATFORM_ADMIN_PWD_ARN: "IsolatedOperatorPass!42",
    }
    if extra:
        initial.update(extra)
    return _InMemorySecretsStore(initial)


def test_first_boot_rotates_default_password_provisions_topology_and_writes_secret() -> None:
    server = _InMemoryCasdoorServer(
        admin_password=CasdoorConstants.FACTORY_DEFAULT_ADMIN_PASSWORD,
        unhealthy_probes=1,
    )
    secrets_store = _make_secrets_store()
    now = [0.0]

    def _clock() -> float:
        return now[0]

    def _sleep(seconds: float) -> None:
        now[0] += seconds

    tokens = iter(["dash01", "dashsec01", "plat02", "platsec02", "m2m03", "m2msec03"])
    bootstrapper = CasdoorCloudBootstrapper(
        config=_make_config(),
        http_client=server,
        secrets_store=secrets_store,
        clock=_clock,
        sleeper=_sleep,
        token_generator=lambda _n: next(tokens),
    )

    result = bootstrapper.run()

    assert result.is_ok
    assert result.value is not None
    summary = result.value
    assert summary.admin_password_rotated is True
    assert summary.secret_updated is True
    assert server.admin_password == "StrongManagedPass!99"
    assert server.authenticated is True

    # Strictly cloud realms only (no local demo realms or demo users)
    assert set(server.orgs) == {"admin/soopa-platform", "admin/soopa-global"}
    assert set(server.users) == {"soopa-platform/platform_admin"}
    platform_admin_user = server.users["soopa-platform/platform_admin"]
    assert platform_admin_user["email"] == "admin@flowwolf.io"
    assert platform_admin_user["isAdmin"] is True
    # Strict privilege separation: operator password must NOT equal IdP root password
    assert platform_admin_user["password"] == "IsolatedOperatorPass!42"
    assert platform_admin_user["password"] != server.admin_password

    # Verify all 3 apps use compact JWT-Custom tokens and exact staging callback + logout URIs
    dash_app = server.apps[f"admin/{CasdoorApplicationName.DASHBOARD.value}"]
    assert dash_app["tokenFormat"] == CasdoorTokenFormat.JWT_CUSTOM.value
    assert dash_app["tokenFields"] == list(CasdoorConstants.MINIMAL_TOKEN_FIELDS)
    assert dash_app["redirectUris"] == [
        "https://dashboard.staging.flowwolf.io/callback",
        "https://dashboard.staging.flowwolf.io",
    ]
    assert dash_app["isShared"] is True
    assert dash_app["enableSignUp"] is True

    platform_app = server.apps[f"admin/{CasdoorApplicationName.PLATFORM_ADMIN.value}"]
    assert platform_app["organization"] == CasdoorRealm.PLATFORM.value
    assert platform_app["isShared"] is False
    assert platform_app["enableSignUp"] is False

    m2m_app = server.apps[f"admin/{CasdoorApplicationName.API_M2M.value}"]
    assert m2m_app["grantTypes"] == [CasdoorGrantType.CLIENT_CREDENTIALS.value]
    assert m2m_app["redirectUris"] == []
    assert m2m_app["enablePassword"] is False

    # Verify Secrets Manager JSON contract
    assert len(secrets_store.put_calls) == 1
    stored_payload = json.loads(
        secrets_store.values["arn:aws:secretsmanager:us-east-1:123:secret:admin-oauth"]
    )
    assert stored_payload == {
        CasdoorAdminOAuthSecretKey.PLATFORM_ADMIN_ID.value: "usr-casdoor-101",
        CasdoorAdminOAuthSecretKey.DASHBOARD_CLIENT_ID.value: "soopa_dashboard_dash01",
        CasdoorAdminOAuthSecretKey.PLATFORM_ADMIN_CLIENT_ID.value: "soopa_platform_admin_plat02",
        CasdoorAdminOAuthSecretKey.ADMIN_CLIENT_ID.value: "soopa_api_m2m_m2m03",
        CasdoorAdminOAuthSecretKey.ADMIN_CLIENT_SECRET.value: "m2msec03",
        CasdoorAdminOAuthSecretKey.IDENTITY_AUDIENCE.value: (
            "soopa_dashboard_dash01,soopa_platform_admin_plat02,soopa_api_m2m_m2m03"
        ),
    }


def test_second_run_is_fully_idempotent_without_password_rotation_or_secret_churn() -> None:
    server = _InMemoryCasdoorServer(admin_password="StrongManagedPass!99")
    secrets_store = _make_secrets_store()
    tokens = iter(["dash01", "dashsec01", "plat02", "platsec02", "m2m03", "m2msec03"])
    bootstrapper = CasdoorCloudBootstrapper(
        config=_make_config(),
        http_client=server,
        secrets_store=secrets_store,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
        token_generator=lambda _n: next(tokens),
    )

    first = bootstrapper.run()
    assert first.is_ok and first.value is not None
    assert first.value.admin_password_rotated is False
    assert first.value.secret_updated is True

    server.requests.clear()
    second = bootstrapper.run()
    assert second.is_ok and second.value is not None
    assert second.value.admin_password_rotated is False
    assert second.value.secret_updated is False
    assert len(secrets_store.put_calls) == 1
    assert ("POST", CasdoorBootstrapEndpoint.SET_PASSWORD.value) not in server.requests
    assert ("POST", CasdoorBootstrapEndpoint.UPDATE_ORGANIZATION.value) not in server.requests
    assert ("POST", CasdoorBootstrapEndpoint.UPDATE_APPLICATION.value) not in server.requests
    assert ("POST", CasdoorBootstrapEndpoint.ADD_USER.value) not in server.requests

    # Simulate drift on a single application and verify only that drifted app is updated
    server.apps[f"admin/{CasdoorApplicationName.DASHBOARD.value}"]["redirectUris"] = []
    server.requests.clear()
    third = bootstrapper.run()
    assert third.is_ok and third.value is not None
    assert server.requests.count(("POST", CasdoorBootstrapEndpoint.UPDATE_APPLICATION.value)) == 1
    assert server.apps[f"admin/{CasdoorApplicationName.DASHBOARD.value}"]["redirectUris"] == [
        "https://dashboard.staging.flowwolf.io/callback",
        "https://dashboard.staging.flowwolf.io",
    ]


def test_non_json_gateway_response_returns_structured_api_error() -> None:
    server = _InMemoryCasdoorServer(return_html_on_login=True)
    secrets_store = _make_secrets_store()
    res = CasdoorCloudBootstrapper(
        config=_make_config(),
        http_client=server,
        secrets_store=secrets_store,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    ).run()
    assert not res.is_ok
    assert res.error is not None
    assert res.error.code == CasdoorBootstrapErrorCode.CASDOOR_API_ERROR
    assert res.error.endpoint == CasdoorBootstrapEndpoint.LOGIN.value


def test_masked_m2m_client_secret_fails_fast_without_corrupting_secrets_manager() -> None:
    server = _InMemoryCasdoorServer(admin_password="StrongManagedPass!99", mask_m2m_secret=True)
    server.apps[f"admin/{CasdoorApplicationName.API_M2M.value}"] = {
        "owner": "admin",
        "name": CasdoorApplicationName.API_M2M.value,
        "clientId": "existing_m2m_id",
        "clientSecret": "real_secret",
    }
    secrets_store = _make_secrets_store(
        {_ADMIN_OAUTH_ARN: json.dumps({"admin_client_secret": "real_secret"})}
    )
    bootstrapper = CasdoorCloudBootstrapper(
        config=_make_config(),
        http_client=server,
        secrets_store=secrets_store,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )

    result = bootstrapper.run()
    assert not result.is_ok
    assert result.error is not None
    assert result.error.code == CasdoorBootstrapErrorCode.MASKED_CLIENT_SECRET
    assert secrets_store.put_calls == []


def test_health_timeout_and_auth_failures_return_structured_errors() -> None:
    # 1. Health timeout
    unhealthy_server = _InMemoryCasdoorServer(unhealthy_probes=99)
    secrets_store = _make_secrets_store()
    now = [0.0]

    def _clock() -> float:
        return now[0]

    def _sleep(seconds: float) -> None:
        now[0] += seconds

    res_timeout = CasdoorCloudBootstrapper(
        config=_make_config(),
        http_client=unhealthy_server,
        secrets_store=secrets_store,
        clock=_clock,
        sleeper=_sleep,
    ).run()
    assert not res_timeout.is_ok
    assert res_timeout.error is not None
    assert res_timeout.error.code == CasdoorBootstrapErrorCode.HEALTH_CHECK_TIMEOUT

    # 2. Neither managed nor factory password accepted
    wrong_pwd_server = _InMemoryCasdoorServer(admin_password="SomeOtherPassword!")
    res_auth = CasdoorCloudBootstrapper(
        config=_make_config(),
        http_client=wrong_pwd_server,
        secrets_store=secrets_store,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    ).run()
    assert not res_auth.is_ok
    assert res_auth.error is not None
    assert res_auth.error.code == CasdoorBootstrapErrorCode.ADMIN_AUTH_FAILED

    # 3. Password rotation error
    fail_rotate_server = _InMemoryCasdoorServer(
        admin_password=CasdoorConstants.FACTORY_DEFAULT_ADMIN_PASSWORD,
        fail_set_password=True,
    )
    res_rotate = CasdoorCloudBootstrapper(
        config=_make_config(),
        http_client=fail_rotate_server,
        secrets_store=secrets_store,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    ).run()
    assert not res_rotate.is_ok
    assert res_rotate.error is not None
    assert res_rotate.error.code == CasdoorBootstrapErrorCode.PASSWORD_ROTATION_FAILED


def test_resolve_bootstrap_config_strips_fqdn_dots_and_validates_required_outputs() -> None:
    def _reader(stack_dir: Path | str, _env: str) -> Mapping[str, str]:
        if str(stack_dir).endswith("casdoor"):
            return {
                "identity_domain": "identity.staging.flowwolf.io.",
                "admin_password_secret_arn": "arn:pwd",
                "platform_admin_password_secret_arn": "arn:plat-pwd",
                "admin_oauth_secret_arn": "arn:oauth",
                "platform_realm": "soopa-platform",
                "global_realm": "soopa-global",
            }
        return {"staging_domain": "staging.flowwolf.io."}

    ok_res = resolve_bootstrap_config(
        env_name="staging",
        stack_output_reader=_reader,
        environ={"COMPANY_DOMAIN": "flowwolf.io"},
    )
    assert ok_res.is_ok and ok_res.value is not None
    assert ok_res.value.identity_base_url == "https://identity.staging.flowwolf.io"
    assert ok_res.value.dashboard_base_url == "https://dashboard.staging.flowwolf.io"
    assert ok_res.value.platform_admin_email == "admin@flowwolf.io"
    assert ok_res.value.platform_admin_password_secret_arn == "arn:plat-pwd"

    bad_res = resolve_bootstrap_config(
        env_name="staging",
        stack_output_reader=lambda _d, _e: {},
        environ={},
    )
    assert not bad_res.is_ok
    assert bad_res.error is not None
    assert bad_res.error.code == CasdoorBootstrapErrorCode.MISSING_STACK_OUTPUT


def test_aws_secrets_manager_adapter_maps_not_found_to_none_and_access_denied_to_error() -> None:
    not_found_adapter = AwsSecretsManagerAdapter(
        _FakeBotoSecretsClient(error_code="ResourceNotFoundException")
    )
    not_found_res = not_found_adapter.get_secret_string("arn:missing")
    assert not_found_res.is_ok
    assert not_found_res.value is None

    denied_adapter = AwsSecretsManagerAdapter(
        _FakeBotoSecretsClient(error_code="AccessDeniedException")
    )
    denied_res = denied_adapter.get_secret_string("arn:denied")
    assert not denied_res.is_ok
    assert denied_res.error is not None
    assert denied_res.error.code == CasdoorBootstrapErrorCode.SECRET_READ_FAILED


def test_corrupt_existing_oauth_secret_fails_fast_without_overwriting() -> None:
    server = _InMemoryCasdoorServer(admin_password="StrongManagedPass!99")
    secrets_store = _make_secrets_store({_ADMIN_OAUTH_ARN: "not-valid-json{{{"})
    res = CasdoorCloudBootstrapper(
        config=_make_config(),
        http_client=server,
        secrets_store=secrets_store,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    ).run()
    assert not res.is_ok
    assert res.error is not None
    assert res.error.code == CasdoorBootstrapErrorCode.SECRET_READ_FAILED
    assert secrets_store.put_calls == []


def test_resolve_bootstrap_config_handles_missing_pulumi_binary_without_raising() -> None:
    def _failing_reader(_stack_dir: Path | str, _env: str) -> Mapping[str, str]:
        raise FileNotFoundError("pulumi binary missing")

    res = resolve_bootstrap_config(
        env_name="staging",
        stack_output_reader=_failing_reader,
        environ={},
    )
    assert not res.is_ok
    assert res.error is not None
    assert res.error.code == CasdoorBootstrapErrorCode.MISSING_STACK_OUTPUT


def test_custom_platform_realm_propagates_to_platform_admin_app_and_user() -> None:
    server = _InMemoryCasdoorServer(admin_password="StrongManagedPass!99")
    secrets_store = _make_secrets_store()
    custom_config = _make_config(
        platform_realm="custom-platform-ops",
        global_realm="custom-global",
    )
    res = CasdoorCloudBootstrapper(
        config=custom_config,
        http_client=server,
        secrets_store=secrets_store,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    ).run()
    assert res.is_ok
    assert set(server.orgs) == {"admin/custom-platform-ops", "admin/custom-global"}
    assert (
        server.apps[f"admin/{CasdoorApplicationName.PLATFORM_ADMIN.value}"]["organization"]
        == "custom-platform-ops"
    )
    assert "custom-platform-ops/platform_admin" in server.users


def test_insecure_http_urls_are_rejected_before_any_network_or_secret_access() -> None:
    server = _InMemoryCasdoorServer()
    secrets_store = _make_secrets_store()
    res = CasdoorCloudBootstrapper(
        config=_make_config(identity_base_url="http://identity.staging.flowwolf.io"),
        http_client=server,
        secrets_store=secrets_store,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    ).run()
    assert not res.is_ok
    assert res.error is not None
    assert res.error.code == CasdoorBootstrapErrorCode.INSECURE_TRANSPORT
    assert server.requests == []
    assert secrets_store.put_calls == []
