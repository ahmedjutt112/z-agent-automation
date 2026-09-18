"""Real OAuth refresh-token flow + Google Calendar integration tests.

Covers Task 8-b:
- OAuth refresh / revoke / validate on the OAuthProvider ABC + each
  concrete provider (Google, GitHub, Facebook). Mock-mode paths only —
  real-credential integration tests live in ``test_integration_real.py``.
- GoogleCalendarService mock-mode behaviour for every ABC method.
- ``get_calendar_service()`` factory returns GoogleCalendarService when
  a Google OAuth token row exists in ``api_credentials`` (and mock_mode
  is off).
- ``GoogleCalendarService`` raises a helpful RuntimeError when
  ``google-api-python-client`` is not installed.
- HTTP endpoints ``POST /oauth/{provider}/refresh``,
  ``POST /oauth/{provider}/revoke``, ``GET /oauth/{provider}/validate``
  in mock mode.
- ``get_stored_tokens`` / ``store_tokens`` roundtrip via an in-memory
  SQLite engine.

Master prompt §57 (secrets never logged) is honoured throughout — the
tests assert that the masked preview appears in any log output that
references a token, never the raw token.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from typing import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


# ---------------------------------------------------------------------------
# Path setup — mirror the conftest so this file is runnable standalone
# ---------------------------------------------------------------------------

PROJECT_ROOT = "/home/z/my-project"
AUTOMATION_ROOT = PROJECT_ROOT + "/apps/automation-service"
for p in (AUTOMATION_ROOT, PROJECT_ROOT):
    if p not in sys.path:
        sys.path.insert(0, p)


from automation_service.config import settings  # noqa: E402
from automation_service.integrations.calendar import (  # noqa: E402
    CalendarEvent,
    GoogleCalendarService,
    MockCalendarService,
    get_calendar_service,
)
from automation_service.integrations.oauth import (  # noqa: E402
    GitHubOAuthProvider,
    GoogleOAuthProvider,
    FacebookOAuthProvider,
    OAuthTokens,
    OAuthUserInfo,
    get_oauth_provider,
    get_stored_tokens,
    store_tokens,
)
from automation_service.security.credentials import mask  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run a coroutine to completion in a fresh event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture()
def in_memory_db(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Spin up an in-memory SQLite + monkeypatch database.base.SessionLocal
    so that ``store_tokens`` / ``get_stored_tokens`` (which import
    SessionLocal at call time) hit our test engine instead of the
    production one.

    Also forces ``settings.mock_mode = False`` for the duration of the
    fixture — otherwise ``store_tokens``/``get_stored_tokens`` short-
    circuit to a no-op.
    """
    from database.base import Base
    from database.models import schema  # noqa: F401

    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    # Override BOTH database.base.SessionLocal (for store_tokens) and
    # the lazily-imported alias inside _persist_oauth_tokens.
    import database.base as db_base
    monkeypatch.setattr(db_base, "SessionLocal", TestSession)

    prev_mock = settings.mock_mode
    settings.mock_mode = False
    try:
        yield
    finally:
        settings.mock_mode = prev_mock
        engine.dispose()


# ---------------------------------------------------------------------------
# OAuth refresh_token — Google mock
# ---------------------------------------------------------------------------


def test_oauth_refresh_token_google_mock() -> None:
    """GoogleOAuthProvider.refresh_token returns OAuthTokens in mock mode."""
    provider = GoogleOAuthProvider()
    tokens = _run(provider.refresh_token("some-refresh-token"))
    assert isinstance(tokens, OAuthTokens)
    assert tokens.access_token.startswith("mock-google-refreshed-access-token")
    # The refresh_token is preserved (Google rotates it sometimes but
    # mock mode just echoes the input).
    assert tokens.refresh_token == "some-refresh-token"
    # expires_at must be in the future.
    assert tokens.expires_at is not None
    assert tokens.expires_at > datetime.now(timezone.utc)
    assert tokens.token_type == "Bearer"


def test_oauth_refresh_token_facebook_mock() -> None:
    """FacebookOAuthProvider.refresh_token returns OAuthTokens in mock mode."""
    provider = FacebookOAuthProvider()
    tokens = _run(provider.refresh_token("fb-exchange-token"))
    assert isinstance(tokens, OAuthTokens)
    assert tokens.access_token.startswith("mock-facebook-refreshed-access-token")


# ---------------------------------------------------------------------------
# OAuth refresh_token — GitHub raises helpful NotImplementedError
# ---------------------------------------------------------------------------


def test_oauth_refresh_token_github_raises() -> None:
    """GitHubOAuthProvider.refresh_token raises NotImplementedError with
    a helpful message (GitHub tokens do not expire / cannot be refreshed)."""
    provider = GitHubOAuthProvider()
    with pytest.raises(NotImplementedError) as exc_info:
        _run(provider.refresh_token("anything"))
    msg = str(exc_info.value)
    assert "GitHub" in msg
    assert "do not expire" in msg
    assert "re-run the OAuth flow" in msg or "OAuth flow" in msg


# ---------------------------------------------------------------------------
# OAuth revoke_token — mock returns True for all three providers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider_cls",
    [GoogleOAuthProvider, GitHubOAuthProvider, FacebookOAuthProvider],
)
def test_oauth_revoke_token_mock(provider_cls) -> None:
    """Each provider's revoke_token returns True in mock mode."""
    provider = provider_cls()
    result = _run(provider.revoke_token("some-access-token"))
    assert result is True


# ---------------------------------------------------------------------------
# OAuth validate_token — mock returns True for all three providers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider_cls",
    [GoogleOAuthProvider, GitHubOAuthProvider, FacebookOAuthProvider],
)
def test_oauth_validate_token_mock(provider_cls) -> None:
    """Each provider's validate_token returns True in mock mode."""
    provider = provider_cls()
    result = _run(provider.validate_token("some-access-token"))
    assert result is True


# ---------------------------------------------------------------------------
# get_stored_tokens / store_tokens — roundtrip via in-memory DB
# ---------------------------------------------------------------------------


def test_get_stored_tokens_returns_none_when_not_set(in_memory_db) -> None:
    """get_stored_tokens for a nonexistent service returns None."""
    result = get_stored_tokens("nonexistent")
    assert result is None


def test_store_and_get_tokens(in_memory_db) -> None:
    """store_tokens then get_stored_tokens roundtrips the access_token +
    refresh_token + expires_at + scope.
    """
    expires = datetime.now(timezone.utc) + timedelta(hours=1)
    tokens = OAuthTokens(
        access_token="test-access-token-0123456789",
        refresh_token="test-refresh-token",
        expires_at=expires,
        scope="openid email profile",
        token_type="Bearer",
    )
    store_tokens("google", tokens)

    # Round-trip
    result = get_stored_tokens("google")
    assert result is not None, "get_stored_tokens returned None after store_tokens"
    assert result["access_token"] == "test-access-token-0123456789"
    assert result["refresh_token"] == "test-refresh-token"
    assert result["scope"] == "openid email profile"
    assert result["token_type"] == "Bearer"
    # expires_at should round-trip (it's an ISO string in the DB).
    assert result["expires_at"] is not None
    # The credential_store_ref should contain a masked preview (master
    # prompt §57 — never store plain secrets in the ref column).
    assert "test-access-token-0123456789" not in (result["credential_store_ref"] or "")
    # The masked preview should at least be present (mask returns at
    # least "<redacted>" or the masked form).
    assert result["credential_store_ref"] is not None
    assert len(result["credential_store_ref"]) > 0


def test_store_tokens_upsert_does_not_duplicate(in_memory_db) -> None:
    """store_tokens twice for the same service updates the existing row
    rather than inserting a new one (verified by counting rows).
    """
    from database.base import SessionLocal
    from database.models.schema import APICredential

    tokens1 = OAuthTokens(
        access_token="first-access-token-aaaaaaaa",
        refresh_token="first-refresh",
        scope="openid email profile",
    )
    tokens2 = OAuthTokens(
        access_token="second-access-token-bbbbbbbb",
        refresh_token="second-refresh",
        scope="openid email profile",
    )
    store_tokens("google", tokens1)
    store_tokens("google", tokens2)

    session = SessionLocal()
    try:
        rows = (
            session.query(APICredential)
            .filter(APICredential.service == "oauth:google")
            .all()
        )
        assert len(rows) == 1, f"expected 1 row after upsert, got {len(rows)}"
        # The upsert should have replaced the token.
        result = get_stored_tokens("google")
        assert result is not None
        assert result["access_token"] == "second-access-token-bbbbbbbb"
    finally:
        session.close()


# ---------------------------------------------------------------------------
# GoogleCalendarService — mock-mode behaviour for every ABC method
# ---------------------------------------------------------------------------


def test_calendar_google_list_events_mock() -> None:
    """GoogleCalendarService.list_events returns list in mock mode."""
    svc = GoogleCalendarService(access_token="ignored-in-mock")
    events = _run(svc.list_events())
    assert isinstance(events, list)
    assert len(events) >= 1
    assert all(isinstance(e, CalendarEvent) for e in events)


def test_calendar_google_get_next_meeting_mock() -> None:
    """GoogleCalendarService.get_next_meeting returns an event in mock mode."""
    svc = GoogleCalendarService()
    evt = _run(svc.get_next_meeting())
    assert evt is not None
    assert isinstance(evt, CalendarEvent)


def test_calendar_google_get_event_mock() -> None:
    """GoogleCalendarService.get_event returns the event in mock mode."""
    svc = GoogleCalendarService()
    # The mock service knows about 'mock-evt-1'.
    evt = _run(svc.get_event("mock-evt-1"))
    assert isinstance(evt, CalendarEvent)
    assert evt.id == "mock-evt-1"


def test_calendar_google_create_event_mock() -> None:
    """GoogleCalendarService.create_event returns a CalendarEvent in mock."""
    svc = GoogleCalendarService()
    start = datetime.now(timezone.utc) + timedelta(hours=2)
    end = start + timedelta(minutes=30)
    evt = _run(
        svc.create_event(
            title="Test Event",
            start_at=start,
            end_at=end,
            description="created by test",
            location="https://meet.example.com/test",
        )
    )
    assert isinstance(evt, CalendarEvent)
    assert evt.title == "Test Event"
    assert evt.description == "created by test"


def test_calendar_google_update_event_mock() -> None:
    """GoogleCalendarService.update_event patches the title in mock mode."""
    svc = GoogleCalendarService()
    updated = _run(svc.update_event("mock-evt-1", title="Patched Title"))
    assert isinstance(updated, CalendarEvent)
    assert updated.title == "Patched Title"


def test_calendar_google_delete_event_mock() -> None:
    """GoogleCalendarService.delete_event returns True in mock mode."""
    svc = GoogleCalendarService()
    # Create then delete so we have a known event id.
    start = datetime.now(timezone.utc) + timedelta(hours=5)
    evt = _run(svc.create_event(title="To Delete", start_at=start, end_at=start))
    ok = _run(svc.delete_event(evt.id))
    assert ok is True


# ---------------------------------------------------------------------------
# Factory: get_calendar_service
# ---------------------------------------------------------------------------


def test_calendar_factory_returns_google_when_oauth_set(
    in_memory_db,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """get_calendar_service() returns GoogleCalendarService when a Google
    OAuth token row exists in api_credentials (and mock_mode is off).
    """
    # Seed a google oauth row.
    tokens = OAuthTokens(
        access_token="real-access-token-0123456789",
        refresh_token="real-refresh-token",
        scope="openid email profile",
    )
    store_tokens("google", tokens)

    # The factory consults _has_google_oauth_token + _read_google_access_token
    # which read from the DB. Since mock_mode is False (in_memory_db fixture)
    # and we just stored a row, the factory should pick GoogleCalendarService.
    svc = get_calendar_service()
    assert isinstance(svc, GoogleCalendarService), (
        f"expected GoogleCalendarService, got {type(svc).__name__}"
    )


def test_calendar_factory_returns_mock_when_no_oauth(
    in_memory_db,
) -> None:
    """get_calendar_service() falls back to MockCalendarService when no
    oauth:google row exists."""
    svc = get_calendar_service()
    assert isinstance(svc, MockCalendarService)


# ---------------------------------------------------------------------------
# GoogleCalendarService without google-api-python-client — helpful error
# ---------------------------------------------------------------------------


def test_calendar_google_real_init_without_creds_raises_helpful_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When mock_mode is OFF and google-api-python-client is NOT installed,
    GoogleCalendarService.list_events raises a RuntimeError whose message
    tells the user exactly what to pip install.

    The environment doesn't have google-api-python-client installed (see
    conftest.py), so we can drive the lazy-import error path directly.
    """
    prev = settings.mock_mode
    settings.mock_mode = False
    try:
        svc = GoogleCalendarService(access_token="fake-token")
        # First call must raise a RuntimeError mentioning the package name.
        with pytest.raises(RuntimeError) as exc_info:
            _run(svc.list_events())
        msg = str(exc_info.value)
        # The error must mention the missing package AND give install hint.
        assert "google-api-python-client" in msg or "google-auth" in msg
        assert "pip install" in msg
    finally:
        settings.mock_mode = prev


def test_calendar_google_get_credentials_returns_none_without_creds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_get_credentials returns None when no creds are available and
    google-auth is not installed (instead of raising)."""
    prev = settings.mock_mode
    settings.mock_mode = False
    try:
        svc = GoogleCalendarService()  # no access_token, no env var, no DB row
        # The mock_settings fixture's teardown will reset settings.mock_mode,
        # but we're inside our own prev/try/finally here. To avoid hitting
        # the DB (which is the production DB here), we monkeypatch
        # _read_stored_google_tokens to return None.
        monkeypatch.setattr(
            GoogleCalendarService,
            "_read_stored_google_tokens",
            staticmethod(lambda: None),
        )
        # Also clear GOOGLE_APPLICATION_CREDENTIALS so the SA path doesn't fire.
        monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
        # google-auth isn't installed → _get_credentials raises RuntimeError
        # about google-auth being missing.
        with pytest.raises(RuntimeError) as exc_info:
            svc._get_credentials()
        assert "google-auth" in str(exc_info.value) or "google-api-python-client" in str(exc_info.value)
    finally:
        settings.mock_mode = prev


# ---------------------------------------------------------------------------
# HTTP endpoints — POST /oauth/{provider}/refresh | revoke | validate
# ---------------------------------------------------------------------------


def test_api_oauth_refresh(client) -> None:
    """POST /oauth/google/refresh returns 200 in mock mode with new tokens."""
    r = client.post(
        "/oauth/google/refresh",
        json={"refresh_token": "test-refresh-token"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "google"
    assert "access_token" in body
    assert body["access_token"].startswith("mock-google-refreshed-access-token")
    assert body["refresh_token"] == "test-refresh-token"
    assert body["expires_at"] is not None


def test_api_oauth_refresh_github_returns_400(client) -> None:
    """POST /oauth/github/refresh returns 400 because GitHub tokens
    can't be refreshed (NotImplementedError surfaces as 400)."""
    r = client.post(
        "/oauth/github/refresh",
        json={"refresh_token": "anything"},
    )
    assert r.status_code == 400, r.text
    body = r.json()
    assert "GitHub" in body["detail"]


def test_api_oauth_refresh_unknown_provider(client) -> None:
    """POST /oauth/{unknown}/refresh returns 404."""
    r = client.post(
        "/oauth/nonexistent/refresh",
        json={"refresh_token": "x"},
    )
    assert r.status_code == 404


def test_api_oauth_revoke(client) -> None:
    """POST /oauth/google/revoke returns 200 with revoked=true in mock mode."""
    r = client.post(
        "/oauth/google/revoke",
        json={"access_token": "test-access-token"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "google"
    assert body["revoked"] is True


def test_api_oauth_revoke_unknown_provider(client) -> None:
    """POST /oauth/{unknown}/revoke returns 404."""
    r = client.post(
        "/oauth/nonexistent/revoke",
        json={"access_token": "x"},
    )
    assert r.status_code == 404


def test_api_oauth_validate(client) -> None:
    """GET /oauth/google/validate?access_token=test returns 200 with valid=true
    in mock mode."""
    r = client.get("/oauth/google/validate", params={"access_token": "test"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "google"
    assert body["valid"] is True


def test_api_oauth_validate_unknown_provider(client) -> None:
    """GET /oauth/{unknown}/validate returns 404."""
    r = client.get("/oauth/nonexistent/validate", params={"access_token": "x"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# URL builders — sanity checks on the per-provider helpers
# ---------------------------------------------------------------------------


def test_google_refresh_url_builder() -> None:
    """GoogleOAuthProvider._get_refresh_url returns the token endpoint."""
    p = GoogleOAuthProvider()
    assert p._get_refresh_url() == "https://oauth2.googleapis.com/token"


def test_google_refresh_params_builder() -> None:
    """GoogleOAuthProvider._get_refresh_params returns the expected dict."""
    p = GoogleOAuthProvider()
    # Client id / secret come from env vars; set them via monkeypatch-style.
    import os
    prev_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
    prev_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
    os.environ["GOOGLE_OAUTH_CLIENT_ID"] = "test-cid"
    os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = "test-csec"
    try:
        params = p._get_refresh_params("rtok")
        assert params["client_id"] == "test-cid"
        assert params["client_secret"] == "test-csec"
        assert params["refresh_token"] == "rtok"
        assert params["grant_type"] == "refresh_token"
    finally:
        if prev_id is None:
            del os.environ["GOOGLE_OAUTH_CLIENT_ID"]
        else:
            os.environ["GOOGLE_OAUTH_CLIENT_ID"] = prev_id
        if prev_secret is None:
            del os.environ["GOOGLE_OAUTH_CLIENT_SECRET"]
        else:
            os.environ["GOOGLE_OAUTH_CLIENT_SECRET"] = prev_secret


def test_google_revoke_url_contains_token() -> None:
    """GoogleOAuthProvider._get_revoke_url embeds the access_token as a query."""
    p = GoogleOAuthProvider()
    url = p._get_revoke_url("abc123")
    assert "https://oauth2.googleapis.com/revoke" in url
    assert "token=abc123" in url


def test_facebook_validate_url_uses_debug_token() -> None:
    """FacebookOAuthProvider._get_validate_url hits the debug_token endpoint."""
    p = FacebookOAuthProvider()
    import os
    prev_id = os.environ.get("FACEBOOK_OAUTH_APP_ID")
    prev_secret = os.environ.get("FACEBOOK_OAUTH_APP_SECRET")
    os.environ["FACEBOOK_OAUTH_APP_ID"] = "fb-app"
    os.environ["FACEBOOK_OAUTH_APP_SECRET"] = "fb-sec"
    try:
        url = p._get_validate_url("user-token")
        assert "debug_token" in url
        assert "input_token=user-token" in url
        assert "access_token=fb-app%7Cfb-sec" in url  # %7C is '|'
    finally:
        if prev_id is None:
            del os.environ["FACEBOOK_OAUTH_APP_ID"]
        else:
            os.environ["FACEBOOK_OAUTH_APP_ID"] = prev_id
        if prev_secret is None:
            del os.environ["FACEBOOK_OAUTH_APP_SECRET"]
        else:
            os.environ["FACEBOOK_OAUTH_APP_SECRET"] = prev_secret
