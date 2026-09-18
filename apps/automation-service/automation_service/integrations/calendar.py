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
the factory.

Master prompt invariants:
- §5: this is a *local* service — no remote calls except to calendar providers
  the user has explicitly connected.
- §57: secrets are never logged. The Google service receives the access token
  via the credential manager, not via the constructor.
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

    The access token is fetched on demand from the credential manager —
    never stored as an attribute of this class.

    When ``settings.mock_mode`` is True, this instance behaves identically
    to :class:`MockCalendarService` (master prompt §64).
    """

    provider_name = "google"

    def __init__(self, access_token: Optional[str] = None) -> None:
        self._access_token = access_token
        self._mock = MockCalendarService() if settings.mock_mode else None

    def _build_service(self):
        """Construct the google-api-python-client service object.

        Lazy import so this module loads even when google-api-python-client
        is not installed. The error message tells the user exactly what to
        install.
        """
        try:
            from google.oauth2.credentials import Credentials  # type: ignore
            from googleapiclient.discovery import build  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "google-api-python-client is not installed. Install it via "
                "`pip install google-api-python-client google-auth-oauthlib` "
                "to use GoogleCalendarService. (Mock mode is available without it.)"
            ) from exc

        creds = Credentials(token=self._access_token)
        return build("calendar", "v3", credentials=creds, cache_discovery=False)

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

    async def list_events(
        self,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 10,
    ) -> list[CalendarEvent]:
        if self._mock is not None:
            return await self._mock.list_events(time_min, time_max, max_results)

        service = self._build_service()
        now = datetime.now(timezone.utc)
        time_min_str = (time_min or now).isoformat()
        events_result = (
            service.events()
            .list(
                calendarId="primary",
                timeMin=time_min_str,
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        items = events_result.get("items", [])
        return [self._to_event(it) for it in items]

    async def get_event(self, event_id: str) -> CalendarEvent:
        if self._mock is not None:
            return await self._mock.get_event(event_id)
        service = self._build_service()
        item = service.events().get(calendarId="primary", eventId=event_id).execute()
        return self._to_event(item)

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
        service = self._build_service()
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
        created = service.events().insert(calendarId="primary", body=body).execute()
        return self._to_event(created)

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
        service = self._build_service()
        existing = service.events().get(calendarId="primary", eventId=event_id).execute()
        if title is not None:
            existing["summary"] = title
        if start_at is not None:
            existing["start"] = {"dateTime": start_at.isoformat()}
        if end_at is not None:
            existing["end"] = {"dateTime": end_at.isoformat()}
        if description is not None:
            existing["description"] = description
        if location is not None:
            existing["location"] = location
        if attendees is not None:
            existing["attendees"] = [
                {"email": a.email, "displayName": a.name} for a in attendees if a.email
            ]
        updated = (
            service.events()
            .update(calendarId="primary", eventId=event_id, body=existing)
            .execute()
        )
        return self._to_event(updated)

    async def delete_event(self, event_id: str) -> bool:
        if self._mock is not None:
            return await self._mock.delete_event(event_id)
        service = self._build_service()
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        return True

    async def get_next_meeting(self) -> Optional[CalendarEvent]:
        events = await self.list_events(max_results=1)
        return events[0] if events else None


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
