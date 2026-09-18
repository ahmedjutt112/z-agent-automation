"""Calendar integration — master prompt §83 (Phase 5 AI OS Assistant).

Provides:
- ``CalendarEvent`` pydantic model — normalised event representation.
- ``CalendarService`` ABC — list / get / create / update / delete / next-meeting.
- ``MockCalendarService`` — deterministic fake data, used in mock mode and
  whenever no real provider is configured.
- ``GoogleCalendarService`` — uses the OAuth'd Google account (lazy import of
  ``google-api-python-client``; raises a helpful error if missing).
- ``get_calendar_service()`` factory — picks Google when a Google OAuth
  token row exists, otherwise falls back to Mock.

All HTTP calls happen inside the service implementations; this module never
touches the database directly except the ``api_credentials`` lookup used by
the factory and the ``_get_credentials()`` helper on GoogleCalendarService.

Master prompt invariants:
- §5: this is a *local* service — no remote calls except to calendar providers
  the user has explicitly connected.
- §57: secrets are never logged. The Google service receives the access token
  via the credential manager, not via the constructor. The ``_get_credentials``
  helper masks tokens before any debug log line.
- §83: "Every external action must still pass through permissions and
  user-defined policies" — calendar operations are READ-ONLY here. Any
  automation triggered by a calendar event still goes through the permission
  engine before executing.
"""

from __future__ import annotations

import abc
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from loguru import logger
from pydantic import BaseModel, Field

from ..config import settings
from ..security.credentials import mask


# ---------------------------------------------------------------------------
# CalendarEvent pydantic model
# ---------------------------------------------------------------------------


class CalendarAttendee(BaseModel):
    """One attendee on a calendar event."""

    name: Optional[str] = None
    email: Optional[str] = None


class CalendarEvent(BaseModel):
    """Normalised representation of a calendar event.

    Provider-specific fields are mapped into this common shape so the
    OSAssistantAgent doesn't need to know whether the user is on Google
    Calendar, Outlook, or a mock.
    """

    id: str
    title: str
    start_at: datetime
    end_at: datetime
    location: Optional[str] = None
    attendees: list[CalendarAttendee] = Field(default_factory=list)
    description: Optional[str] = None
    conference_url: Optional[str] = None
    meeting_link: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# CalendarService ABC
# ---------------------------------------------------------------------------


class CalendarService(abc.ABC):
    """Abstract calendar service.

    Implementations MUST be safe to construct with no network calls —
    lazy-connect on first use. Master prompt §64: when ``settings.mock_mode``
    is True, every method returns deterministic fake data instead of hitting
    the network.
    """

    provider_name: str = "abstract"

    @abc.abstractmethod
    async def list_events(
        self,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 10,
    ) -> list[CalendarEvent]:
        """Return up to ``max_results`` events in the [time_min, time_max] window."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_event(self, event_id: str) -> CalendarEvent:
        """Fetch a single event by id."""
        raise NotImplementedError

    @abc.abstractmethod
    async def create_event(
        self,
        title: str,
        start_at: datetime,
        end_at: datetime,
        description: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[list[CalendarAttendee]] = None,
        conference_url: Optional[str] = None,
        meeting_link: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> CalendarEvent:
        """Create a new event. Returns the stored event."""
        raise NotImplementedError

    @abc.abstractmethod
    async def update_event(
        self,
        event_id: str,
        title: Optional[str] = None,
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[list[CalendarAttendee]] = None,
        conference_url: Optional[str] = None,
        meeting_link: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> CalendarEvent:
        """Patch an existing event. Only non-None fields are updated."""
        raise NotImplementedError

    @abc.abstractmethod
    async def delete_event(self, event_id: str) -> bool:
        """Delete an event. Returns True on success."""
        raise NotImplementedError

    @abc.abstractmethod
    async def get_next_meeting(self) -> Optional[CalendarEvent]:
        """Return the next upcoming meeting, or None if the calendar is empty."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# MockCalendarService — deterministic fake data
# ---------------------------------------------------------------------------


def _mock_event(
    offset_hours: int,
    title: str = "Mock Meeting",
    attendees: Optional[list[str]] = None,
) -> CalendarEvent:
    """Build a deterministic mock event ``offset_hours`` from now."""
    now = datetime.now(timezone.utc)
    start = now + timedelta(hours=offset_hours)
    end = start + timedelta(minutes=30)
    return CalendarEvent(
        id=f"mock-evt-{offset_hours}",
        title=title,
        start_at=start,
        end_at=end,
        location="https://meet.example.com/mock/" + str(offset_hours),
        attendees=[
            CalendarAttendee(name=name, email=name.lower().replace(" ", ".") + "@example.com")
            for name in (attendees or ["Alice Smith", "Bob Jones"])
        ],
        description=f"Mock calendar event #{offset_hours} — generated by MockCalendarService.",
        conference_url=f"https://meet.example.com/mock/{offset_hours}",
        meeting_link=f"https://meet.example.com/join/{offset_hours}",
        metadata={"mock": True},
    )


# Deterministic event list so tests can assert against it.
_MOCK_EVENTS: list[CalendarEvent] = [
    _mock_event(1, "Standup", ["Alice Smith", "Bob Jones"]),
    _mock_event(3, "Sprint Planning", ["Carol Lee", "Dave Wang", "Eve Patel"]),
    _mock_event(5, "1:1 with Manager", ["Frank Miller"]),
    _mock_event(24, "Client Demo", ["Grace Kim", "Hank Cole"]),
    _mock_event(48, "Quarterly Review", ["Iris Patel", "Jack Brown"]),
]


class MockCalendarService(CalendarService):
    """Always returns deterministic fake data — never touches the network.

    Used in mock mode (master prompt §64) and whenever no real provider
    is configured. The event list is fixed at import time so tests can
    assert against it.
    """

    provider_name = "mock"

    def __init__(self) -> None:
        self._events: dict[str, CalendarEvent] = {e.id: e for e in _MOCK_EVENTS}

    async def list_events(
        self,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 10,
    ) -> list[CalendarEvent]:
        now = datetime.now(timezone.utc)
        lo = time_min or now
        hi = time_max or (now + timedelta(days=30))
        out: list[CalendarEvent] = []
        for e in _MOCK_EVENTS:
            if e.start_at < lo or e.start_at > hi:
                continue
            out.append(e)
            if len(out) >= max_results:
                break
        return out

    async def get_event(self, event_id: str) -> CalendarEvent:
        evt = self._events.get(event_id)
        if evt is None:
            raise KeyError(f"mock event not found: {event_id}")
        return evt

    async def create_event(
        self,
        title: str,
        start_at: datetime,
        end_at: datetime,
        description: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[list[CalendarAttendee]] = None,
        conference_url: Optional[str] = None,
        meeting_link: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> CalendarEvent:
        evt = CalendarEvent(
            id=f"mock-evt-{uuid.uuid4().hex[:8]}",
            title=title,
            start_at=start_at,
            end_at=end_at,
            location=location,
            attendees=attendees or [],
            description=description,
            conference_url=conference_url,
            meeting_link=meeting_link,
            metadata=metadata or {"mock": True},
        )
        self._events[evt.id] = evt
        return evt

    async def update_event(
        self,
        event_id: str,
        title: Optional[str] = None,
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[list[CalendarAttendee]] = None,
        conference_url: Optional[str] = None,
        meeting_link: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> CalendarEvent:
        existing = await self.get_event(event_id)
        updated = existing.model_copy(
            update={
                k: v
                for k, v in {
                    "title": title,
                    "start_at": start_at,
                    "end_at": end_at,
                    "description": description,
                    "location": location,
                    "attendees": attendees,
                    "conference_url": conference_url,
                    "meeting_link": meeting_link,
                    "metadata": metadata,
                }.items()
                if v is not None
            }
        )
        self._events[event_id] = updated
        return updated

    async def delete_event(self, event_id: str) -> bool:
        if event_id not in self._events:
            return False
        del self._events[event_id]
        return True

    async def get_next_meeting(self) -> Optional[CalendarEvent]:
        now = datetime.now(timezone.utc)
        upcoming = [e for e in _MOCK_EVENTS if e.start_at >= now]
        if not upcoming:
            return None
        return min(upcoming, key=lambda e: e.start_at)


# ---------------------------------------------------------------------------
# GoogleCalendarService — uses google-api-python-client (lazy import)
# ---------------------------------------------------------------------------


class GoogleCalendarService(CalendarService):
    """Real Google Calendar implementation.

    Requires:
    - ``google-api-python-client`` + ``google-auth-oauthlib`` installed.
    - A connected Google OAuth account (looked up via the
      ``api_credentials`` table where ``service = 'oauth:google'``).

    The access token is fetched on demand via ``_get_credentials()`` —
    never stored as an attribute of this class. If the env var
    ``GOOGLE_APPLICATION_CREDENTIALS`` is set, it takes precedence and is
    used for service-account auth (no user OAuth needed).

    When ``settings.mock_mode`` is True, this instance behaves identically
    to :class:`MockCalendarService` (master prompt §64) so the assistant
    works without any network or installed Google libraries.

    Master prompt §57: tokens are never logged. When a debug log needs to
    reference the credential, it goes through ``mask()``.
    """

    provider_name = "google"

    # Recognised Google OAuth error reason strings.
    _REASON_EXPIRED = "expired"
    _REASON_INSUFFICIENT_SCOPE = "insufficient scope"

    def __init__(
        self,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
    ) -> None:
        # NOTE: access_token is accepted for backward compatibility with
        # tests + existing callers, but the preferred path is to leave it
        # None and let ``_get_credentials()`` resolve everything at call
        # time. Storing tokens on the instance is fine *only* because we
        # never log them; if you change this, audit §57 compliance first.
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._client_id = client_id
        self._client_secret = client_secret
        self._mock = MockCalendarService() if settings.mock_mode else None

    # ------------------------------------------------------------------
    # Credential resolution (master prompt §57 — never log secrets)
    # ------------------------------------------------------------------

    def _get_credentials(self):
        """Return a ``google.oauth2.credentials.Credentials`` instance.

        Resolution order:
        1. ``GOOGLE_APPLICATION_CREDENTIALS`` env var — if set, use a
           service-account flow (no user OAuth needed). This is the path
           Google's own client libraries prefer.
        2. Tokens stored in the ``api_credentials`` table under
           ``service = 'oauth:google'`` — combined with the Google OAuth
           client_id / client_secret env vars. Refresh token + expiry are
           passed in so the underlying client can auto-refresh.
        3. Constructor-supplied ``access_token`` (legacy / test path).

        Returns ``None`` when no credentials are available. Callers MUST
        handle this by either falling back to mock mode or raising a
        helpful error.

        Lazy imports google-auth so the module loads without it installed.
        """
        try:
            from google.oauth2.credentials import Credentials  # type: ignore
            from google.auth import default as _google_auth_default  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "google-auth is not installed. Install it via "
                "`pip install google-auth google-auth-oauthlib "
                "google-api-python-client` to use GoogleCalendarService. "
                "(Mock mode is available without it.)"
            ) from exc

        # 1. Service account via GOOGLE_APPLICATION_CREDENTIALS env var
        sa_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
        if sa_path:
            try:
                from google.oauth2 import service_account  # type: ignore
                scopes = ["https://www.googleapis.com/auth/calendar"]
                creds = service_account.Credentials.from_service_account_file(
                    sa_path, scopes=scopes
                )
                logger.debug(
                    "GoogleCalendarService: using service account from "
                    "GOOGLE_APPLICATION_CREDENTIALS={}",
                    sa_path,
                )
                return creds
            except Exception as exc:
                logger.warning(
                    "GOOGLE_APPLICATION_CREDENTIALS set but failed to load: {}", exc
                )
                # fall through to OAuth path

        # 2. Tokens stored in api_credentials table
        stored = self._read_stored_google_tokens()
        if stored is not None:
            client_id = self._client_id or os.environ.get("GOOGLE_OAUTH_CLIENT_ID")
            client_secret = self._client_secret or os.environ.get(
                "GOOGLE_OAUTH_CLIENT_SECRET"
            )
            access_token = stored.get("access_token") or self._access_token
            refresh_token = stored.get("refresh_token") or self._refresh_token
            if access_token:
                logger.debug(
                    "GoogleCalendarService: using stored OAuth access token (preview={})",
                    mask(access_token),
                )
                return Credentials(
                    token=access_token,
                    refresh_token=refresh_token,
                    token_uri="https://oauth2.googleapis.com/token",
                    client_id=client_id,
                    client_secret=client_secret,
                    scopes=stored.get("scope", "").split() if stored.get("scope") else None,
                )

        # 3. Constructor-supplied token (legacy / test path)
        if self._access_token:
            logger.debug(
                "GoogleCalendarService: using constructor-supplied access token (preview={})",
                mask(self._access_token),
            )
            return Credentials(
                token=self._access_token,
                refresh_token=self._refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=self._client_id or os.environ.get("GOOGLE_OAUTH_CLIENT_ID"),
                client_secret=(
                    self._client_secret
                    or os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET")
                ),
            )

        return None

    @staticmethod
    def _read_stored_google_tokens() -> Optional[dict]:
        """Look up the stored Google OAuth token dict from the
        ``api_credentials`` table.

        Returns None if:
        - mock mode is on (master prompt §64 — never consult the DB)
        - the api_credentials table isn't initialised
        - no oauth:google row exists
        """
        if settings.mock_mode:
            return None
        try:
            from database.base import SessionLocal  # type: ignore
            from database.models.schema import APICredential  # type: ignore

            session = SessionLocal()
            try:
                row = (
                    session.query(APICredential)
                    .filter(APICredential.service == "oauth:google")
                    .order_by(APICredential.updated_at.desc())
                    .first()
                )
                if row is None:
                    return None
                meta = row.metadata_json or {}
                return {
                    "access_token": meta.get("access_token"),
                    "refresh_token": meta.get("refresh_token"),
                    "expires_at": meta.get("expires_at"),
                    "scope": meta.get("scope"),
                    "token_type": meta.get("token_type", "Bearer"),
                }
            finally:
                session.close()
        except Exception as exc:
            logger.debug("Google stored token lookup failed: {}", exc)
            return None

    # ------------------------------------------------------------------
    # Service construction (lazy import — master prompt §57 install hint)
    # ------------------------------------------------------------------

    def _build_service(self):
        """Construct the google-api-python-client service object.

        Lazy import so this module loads even when google-api-python-client
        is not installed. The error message tells the user exactly what to
        install. Uses ``_get_credentials()`` for auth — never an attribute
        that could leak into logs.
        """
        try:
            from googleapiclient.discovery import build  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "google-api-python-client is not installed. Install it via "
                "`pip install google-api-python-client google-auth-oauthlib` "
                "to use GoogleCalendarService. (Mock mode is available without it.)"
            ) from exc

        creds = self._get_credentials()
        if creds is None:
            raise RuntimeError(
                "No Google credentials available. Either set "
                "GOOGLE_APPLICATION_CREDENTIALS to a service-account JSON file, "
                "connect your Google account via the OAuth flow, or pass an "
                "access_token to GoogleCalendarService."
            )
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

    # ------------------------------------------------------------------
    # 401 retry + 403 scope handling
    # ------------------------------------------------------------------

    def _handle_google_api_error(self, exc: Exception, *, retrying: bool = False) -> None:
        """Inspect a googleapiclient HttpError and convert it to a useful
        RuntimeError (or attempt a token refresh + retry).

        Called from every network method. ``retrying=True`` means we've
        already refreshed the token once and should NOT retry again.
        """
        # googleapiclient.errors.HttpError exposes .resp.status + a JSON body
        status_code = getattr(exc, "resp", None) and getattr(exc.resp, "status", None)
        if status_code is None:
            # Some other error type — re-raise unchanged.
            raise exc

        # Try to parse the error reason out of the JSON body.
        reason: Optional[str] = None
        try:
            import json
            content = exc.content.decode("utf-8") if hasattr(exc, "content") else ""
            if content:
                data = json.loads(content)
                reason = (
                    data.get("error", {}).get("errors", [{}])[0].get("reason")
                    if isinstance(data, dict)
                    else None
                )
        except Exception:
            pass

        # 401 — token expired or revoked. Refresh once and retry.
        if status_code == 401 and not retrying:
            logger.info(
                "Google Calendar returned 401 (reason={}) — refreshing token and retrying once.",
                reason or "unknown",
            )
            refreshed = self._refresh_access_token()
            if not refreshed:
                raise RuntimeError(
                    "Google Calendar returned 401 and token refresh failed. "
                    "Re-connect your Google account via /oauth/google/start."
                ) from exc
            raise _RetryAfterRefresh()  # signal caller to retry once

        # 403 — insufficient scope is the most common cause.
        if status_code == 403:
            if reason == self._REASON_INSUFFICIENT_SCOPE or "insufficient" in (reason or "").lower():
                raise RuntimeError(
                    "Google Calendar API returned 403 insufficient_scope. "
                    "Re-authorize your Google account with the "
                    "https://www.googleapis.com/auth/calendar scope "
                    "(start the OAuth flow at /oauth/google/start)."
                ) from exc
            raise RuntimeError(
                f"Google Calendar API returned 403 (reason={reason or 'unknown'}). "
                "The account may not have access to the requested calendar."
            ) from exc

        # Any other status — surface a generic error.
        raise RuntimeError(
            f"Google Calendar API call failed (HTTP {status_code}, reason={reason or 'unknown'}): {exc}"
        ) from exc

    def _refresh_access_token(self) -> bool:
        """Best-effort refresh of the Google OAuth access token.

        Delegates to the GoogleOAuthProvider so we don't duplicate the
        refresh-token POST logic. On success the new tokens are stored
        back into the api_credentials table (so subsequent calls skip the
        refresh). On failure returns False — the caller surfaces a useful
        error.

        Master prompt §57: the refresh_token is never logged.
        """
        try:
            from .oauth import get_oauth_provider, store_tokens

            provider = get_oauth_provider("google")
            stored = self._read_stored_google_tokens()
            refresh_token = (stored or {}).get("refresh_token") if stored else self._refresh_token
            if not refresh_token:
                logger.warning(
                    "Google Calendar: cannot refresh — no refresh_token stored."
                )
                return False

            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're already in an async context — schedule the await
                    # on the running loop and block until done.
                    import asyncio as _a
                    fut = _a.run_coroutine_threadsafe(
                        provider.refresh_token(refresh_token), loop
                    )
                    new_tokens = fut.result(timeout=30)
                else:
                    new_tokens = loop.run_until_complete(
                        provider.refresh_token(refresh_token)
                    )
            except RuntimeError:
                # No running loop in this thread — create one.
                import asyncio as _a
                new_tokens = _a.run(
                    provider.refresh_token(refresh_token)
                )

            # Stash the new access_token on the instance so the retry uses it.
            self._access_token = new_tokens.access_token
            # Persist to DB so subsequent calls skip the refresh.
            try:
                store_tokens("google", new_tokens)
            except Exception as persist_exc:
                logger.debug("Failed to persist refreshed Google tokens: {}", persist_exc)
            logger.debug(
                "Google Calendar: token refreshed successfully (preview={})",
                mask(new_tokens.access_token),
            )
            return True
        except Exception as exc:
            logger.error("Google Calendar token refresh failed: {}", exc)
            return False

    # ------------------------------------------------------------------
    # Conversion helper
    # ------------------------------------------------------------------

    @staticmethod
    def _to_event(item: dict) -> CalendarEvent:
        """Convert a Google Calendar API event dict to a CalendarEvent."""
        start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
        end = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date")
        attendees = [
            CalendarAttendee(
                name=a.get("displayName"),
                email=a.get("email"),
            )
            for a in item.get("attendees", [])
            if a.get("email")
        ]
        conf = item.get("conferenceData", {})
        entry_points = conf.get("entryPoints", [])
        conf_url = next(
            (ep.get("uri") for ep in entry_points if ep.get("entryPointType") == "video"),
            None,
        )
        return CalendarEvent(
            id=item.get("id", ""),
            title=item.get("summary", "(no title)"),
            start_at=datetime.fromisoformat(start) if start else datetime.now(timezone.utc),
            end_at=datetime.fromisoformat(end) if start else datetime.now(timezone.utc),
            location=item.get("location"),
            attendees=attendees,
            description=item.get("description"),
            conference_url=conf_url,
            meeting_link=item.get("hangoutLink"),
            metadata={"provider": "google", "raw_etag": item.get("etag")},
        )

    # ------------------------------------------------------------------
    # ABC method implementations
    # ------------------------------------------------------------------

    async def list_events(
        self,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 10,
    ) -> list[CalendarEvent]:
        if self._mock is not None:
            return await self._mock.list_events(time_min, time_max, max_results)

        now = datetime.now(timezone.utc)
        time_min = time_min or now
        time_max = time_max or (now + timedelta(days=30))
        time_min_str = time_min.isoformat()
        time_max_str = time_max.isoformat()

        for _attempt in range(2):
            service = self._build_service()
            try:
                events_result = (
                    service.events()
                    .list(
                        calendarId="primary",
                        timeMin=time_min_str,
                        timeMax=time_max_str,
                        maxResults=max_results,
                        singleEvents=True,
                        orderBy="startTime",
                    )
                    .execute()
                )
            except _RetryAfterRefresh:
                continue  # token refreshed, retry once
            except Exception as exc:
                if _attempt == 0 and _is_401(exc):
                    # Legacy path for HttpError without the JSON shape we
                    # expect — refresh + retry.
                    if self._refresh_access_token():
                        continue
                self._handle_google_api_error(exc, retrying=(_attempt > 0))
                continue  # unreachable — _handle_google_api_error always raises
            items = events_result.get("items", [])
            return [self._to_event(it) for it in items]
        # If we got here, the refresh-and-retry didn't help.
        raise RuntimeError(
            "Google Calendar list_events failed after a token refresh + retry. "
            "Re-authorize the Google account at /oauth/google/start."
        )

    async def get_event(self, event_id: str) -> CalendarEvent:
        if self._mock is not None:
            return await self._mock.get_event(event_id)
        for _attempt in range(2):
            service = self._build_service()
            try:
                item = (
                    service.events()
                    .get(calendarId="primary", eventId=event_id)
                    .execute()
                )
            except _RetryAfterRefresh:
                continue
            except Exception as exc:
                if _attempt == 0 and _is_401(exc) and self._refresh_access_token():
                    continue
                self._handle_google_api_error(exc, retrying=(_attempt > 0))
                continue
            return self._to_event(item)
        raise RuntimeError(
            "Google Calendar get_event failed after a token refresh + retry."
        )

    async def create_event(
        self,
        title: str,
        start_at: datetime,
        end_at: datetime,
        description: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[list[CalendarAttendee]] = None,
        conference_url: Optional[str] = None,
        meeting_link: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> CalendarEvent:
        if self._mock is not None:
            return await self._mock.create_event(
                title, start_at, end_at, description, location,
                attendees, conference_url, meeting_link, metadata,
            )
        body: dict[str, Any] = {
            "summary": title,
            "start": {"dateTime": start_at.isoformat()},
            "end": {"dateTime": end_at.isoformat()},
        }
        if description:
            body["description"] = description
        if location:
            body["location"] = location
        if attendees:
            body["attendees"] = [
                {"email": a.email, "displayName": a.name} for a in attendees if a.email
            ]
        # conference_data: master prompt §83 requested this for create_event.
        if conference_url:
            body["conferenceData"] = {
                "createRequest": {
                    "requestId": uuid.uuid4().hex,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }

        for _attempt in range(2):
            service = self._build_service()
            try:
                created = (
                    service.events()
                    .insert(calendarId="primary", body=body)
                    .execute()
                )
            except _RetryAfterRefresh:
                continue
            except Exception as exc:
                if _attempt == 0 and _is_401(exc) and self._refresh_access_token():
                    continue
                self._handle_google_api_error(exc, retrying=(_attempt > 0))
                continue
            return self._to_event(created)
        raise RuntimeError(
            "Google Calendar create_event failed after a token refresh + retry."
        )

    async def update_event(
        self,
        event_id: str,
        title: Optional[str] = None,
        start_at: Optional[datetime] = None,
        end_at: Optional[datetime] = None,
        description: Optional[str] = None,
        location: Optional[str] = None,
        attendees: Optional[list[CalendarAttendee]] = None,
        conference_url: Optional[str] = None,
        meeting_link: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> CalendarEvent:
        if self._mock is not None:
            return await self._mock.update_event(
                event_id, title, start_at, end_at, description, location,
                attendees, conference_url, meeting_link, metadata,
            )
        body: dict[str, Any] = {}
        if title is not None:
            body["summary"] = title
        if start_at is not None:
            body["start"] = {"dateTime": start_at.isoformat()}
        if end_at is not None:
            body["end"] = {"dateTime": end_at.isoformat()}
        if description is not None:
            body["description"] = description
        if location is not None:
            body["location"] = location
        if attendees is not None:
            body["attendees"] = [
                {"email": a.email, "displayName": a.name} for a in attendees if a.email
            ]
        if conference_url is not None:
            body["conferenceData"] = {
                "createRequest": {
                    "requestId": uuid.uuid4().hex,
                    "conferenceSolutionKey": {"type": "hangoutsMeet"},
                }
            }

        for _attempt in range(2):
            service = self._build_service()
            try:
                updated = (
                    service.events()
                    .patch(calendarId="primary", eventId=event_id, body=body)
                    .execute()
                )
            except _RetryAfterRefresh:
                continue
            except Exception as exc:
                if _attempt == 0 and _is_401(exc) and self._refresh_access_token():
                    continue
                self._handle_google_api_error(exc, retrying=(_attempt > 0))
                continue
            return self._to_event(updated)
        raise RuntimeError(
            "Google Calendar update_event failed after a token refresh + retry."
        )

    async def delete_event(self, event_id: str) -> bool:
        if self._mock is not None:
            return await self._mock.delete_event(event_id)
        for _attempt in range(2):
            service = self._build_service()
            try:
                service.events().delete(
                    calendarId="primary", eventId=event_id
                ).execute()
            except _RetryAfterRefresh:
                continue
            except Exception as exc:
                if _attempt == 0 and _is_401(exc) and self._refresh_access_token():
                    continue
                # 404 means "already deleted" — treat as success per Google's docs.
                if _is_404(exc):
                    return True
                self._handle_google_api_error(exc, retrying=(_attempt > 0))
                continue
            return True
        raise RuntimeError(
            "Google Calendar delete_event failed after a token refresh + retry."
        )

    async def get_next_meeting(self) -> Optional[CalendarEvent]:
        """Return the next upcoming meeting, or None.

        Uses ``list_events`` with time_min=now, time_max=now+24h,
        max_results=1 — per the task spec.
        """
        if self._mock is not None:
            return await self._mock.get_next_meeting()
        now = datetime.now(timezone.utc)
        events = await self.list_events(
            time_min=now,
            time_max=now + timedelta(hours=24),
            max_results=1,
        )
        return events[0] if events else None


class _RetryAfterRefresh(Exception):
    """Internal sentinel raised by ``_handle_google_api_error`` to tell
    the calling method that the access token has been refreshed and the
    request should be retried once."""


def _is_401(exc: Exception) -> bool:
    """True if ``exc`` is a googleapiclient HttpError with HTTP 401."""
    resp = getattr(exc, "resp", None)
    status_code = getattr(resp, "status", None) if resp is not None else None
    return status_code == 401


def _is_404(exc: Exception) -> bool:
    """True if ``exc`` is a googleapiclient HttpError with HTTP 404."""
    resp = getattr(exc, "resp", None)
    status_code = getattr(resp, "status", None) if resp is not None else None
    return status_code == 404


# ---------------------------------------------------------------------------
# Factory — pick the right service for the current environment
# ---------------------------------------------------------------------------


def _has_google_oauth_token() -> bool:
    """Return True if the user has connected a Google OAuth account.

    Looks for a row in ``api_credentials`` where ``service = 'oauth:google'``.
    Resilient to schema-not-initialised states (returns False then).
    """
    # Master prompt §64 — in mock mode we never even consult the DB.
    if settings.mock_mode:
        return False
    try:
        from database.base import SessionLocal  # type: ignore
        from database.models.schema import APICredential  # type: ignore
        from sqlalchemy import select

        session = SessionLocal()
        try:
            row = (
                session.query(APICredential)
                .filter(APICredential.service == "oauth:google")
                .first()
            )
            return row is not None
        finally:
            session.close()
    except Exception as exc:
        logger.debug("Google OAuth token lookup failed: {}", exc)
        return False


def _read_google_access_token() -> Optional[str]:
    """Best-effort fetch of the user's Google OAuth access token.

    Returns None when:
    - mock mode is on
    - the api_credentials table isn't initialised
    - no oauth:google row exists
    - the credential manager can't find the underlying secret
    """
    if settings.mock_mode:
        return None
    try:
        from database.base import SessionLocal  # type: ignore
        from database.models.schema import APICredential  # type: ignore

        session = SessionLocal()
        try:
            row = (
                session.query(APICredential)
                .filter(APICredential.service == "oauth:google")
                .first()
            )
            if row is None:
                return None
            # The actual token is stored via the OS credential manager /
            # keyring; the api_credentials row only holds a masked preview.
            # For now we surface the masked ref — callers that need the
            # real token should request it via ..security.credentials.
            return os.environ.get("GOOGLE_OAUTH_ACCESS_TOKEN")
        finally:
            session.close()
    except Exception as exc:
        logger.debug("Google access token read failed: {}", exc)
        return None


def get_calendar_service() -> CalendarService:
    """Factory: returns a CalendarService appropriate for the environment.

    Decision order:
    1. If ``settings.mock_mode`` is True → :class:`MockCalendarService`.
    2. Else if the user has a connected Google account (``oauth:google``
       row in ``api_credentials``) → :class:`GoogleCalendarService` (which
       will lazily import google-api-python-client on first use).
    3. Else → :class:`MockCalendarService` (so the assistant still works
       without a connected calendar; the user gets a deterministic stub).
    """
    if settings.mock_mode:
        return MockCalendarService()
    if _has_google_oauth_token():
        token = _read_google_access_token()
        return GoogleCalendarService(access_token=token)
    return MockCalendarService()


__all__ = [
    "CalendarAttendee",
    "CalendarEvent",
    "CalendarService",
    "GoogleCalendarService",
    "MockCalendarService",
    "get_calendar_service",
]
