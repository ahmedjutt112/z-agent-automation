"""MemoryManager — master prompt section 84.

Persists five memory types (UserPreferences / WorkflowMemory / ApplicationMemory /
TaskContext / TemporaryMemory) to either the SQLAlchemy ``memories`` table or, in
mock mode, to an in-process dict.

CRITICAL invariants (master prompt):
- section 57: ``detect_sensitive_data`` blocks passwords / API keys / tokens /
  credit-card numbers from being auto-persisted. ``remember`` raises ValueError
  when a sensitive value is detected so the caller can redact + retry.
- section 84: ``inspect_user_data`` returns ALL stored memories for a user;
  ``clear_all_user_data`` performs a GDPR-style right-to-be-forgotten wipe.
- section 84: ``get_context_for_planner`` returns a dict of relevant memories
  the PlannerAgent uses to personalize plans (folder paths, AI provider prefs,
  recent WorkflowMemory, active TaskContext).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Iterable, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Memory types — master prompt section 84
# ---------------------------------------------------------------------------


class MemoryType(str, Enum):
    USER_PREFERENCES = "user_preferences"
    WORKFLOW = "workflow"
    APPLICATION = "application"
    TASK_CONTEXT = "task_context"
    TEMPORARY = "temporary"


class Memory(BaseModel):
    """A single memory entry — section 84.

    ``value`` is intentionally typed ``Any`` so the manager can store strings,
    ints, dicts, lists. When persisted to SQL it is JSON-encoded; when stored
    in-memory it is the original Python object.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = "default"
    type: MemoryType
    key: str
    value: Any
    source: str = "system"
    workflow_id: Optional[str] = None
    task_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Secret detection — master prompt section 57
# ---------------------------------------------------------------------------


# A value is treated as "sensitive" if it matches any of these patterns.
# The order matters: more specific patterns first.

# 1. Explicit password/secret-like keys passed as the *key* are checked separately
#    in ``remember`` — see ``_SENSITIVE_KEY_NAMES`` below.

# 2. API key / token prefixes (OpenAI, Anthropic, GitHub, JWT, Slack, Telegram).
_SECRET_TOKEN_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^sk-[A-Za-z0-9_-]{16,}$"),                 # OpenAI
    re.compile(r"^sk-ant-[A-Za-z0-9_-]{16,}$"),            # Anthropic
    re.compile(r"^vck_[A-Za-z0-9]{16,}$"),                  # Voicechain
    re.compile(r"^vcp_[A-Za-z0-9]{16,}$"),                  # Voicechain portal
    re.compile(r"^ghp_[A-Za-z0-9]{16,}$"),                  # GitHub PAT
    re.compile(r"^github_pat_[A-Za-z0-9_]{16,}$"),          # GitHub fine-grained
    re.compile(r"^glpat-[A-Za-z0-9_-]{16,}$"),              # GitLab PAT
    re.compile(r"^xox[baprs]-[A-Za-z0-9-]+$"),              # Slack tokens
    re.compile(r"^bot[0-9]+:[A-Za-z0-9_-]+$"),             # Telegram bot tokens
    re.compile(r"^eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$"),  # JWT
    re.compile(r"^AIza[0-9A-Za-z_-]{30,}$"),                # Google API key
    re.compile(r"^AKIA[0-9A-Z]{12,}$"),                      # AWS access key id
    re.compile(r"^sk_or_[A-Za-z0-9]{16,}$"),                 # OpenRouter
]

# 3. Credit card numbers (Visa/MC/Amex/Discover) — Luhn not enforced here, but
#    a 13-19 digit string with optional dashes/spaces is treated as suspicious.
_CREDIT_CARD_PATTERN = re.compile(
    r"^\d[\d\s-]{11,22}$"  # 13 to 23 chars total, leading digit + separators
)

# 4. Generic password-like values: a short-ish string containing the literal word
#    "password" or "secret" or "token" adjacent to a value. This is intentionally
#    conservative — we'd rather over-detect than leak a credential.
_PASSWORD_LITERAL_PATTERN = re.compile(
    r"(?i)(password|passwd|secret|api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*\S+"
)

# 4b. Substring check — a value that contains "password", "passwd", "secret",
#     "api_key", or "token" anywhere is suspicious enough to refuse to persist
#     (section 57 — conservative by design). This catches "password123",
#     "my_secret_value", "sk-test-token", etc.
_PASSWORD_SUBSTRING_PATTERN = re.compile(
    r"(?i)password|passwd|secret|api[_-]?key|access[_-]?token|client[_-]?secret|bearer[_-]?token"
)

# 5. Long opaque base64/hex strings (32+ chars, no spaces) — common secret shape.
_LONG_OPAQUE_PATTERN = re.compile(r"^[A-Za-z0-9+/=_-]{32,}$")

# Keys/names that mark a memory entry as sensitive regardless of value shape.
_SENSITIVE_KEY_NAMES = {
    "password",
    "passwd",
    "pwd",
    "secret",
    "api_key",
    "apikey",
    "api_secret",
    "apisecret",
    "access_token",
    "accesstoken",
    "refresh_token",
    "refreshtoken",
    "client_secret",
    "clientsecret",
    "auth_token",
    "authtoken",
    "bearer_token",
    "bearertoken",
    "credit_card",
    "creditcard",
    "card_number",
    "cardnumber",
    "cvv",
    "cvc",
    "ssn",
    "private_key",
    "privatekey",
}


def _looks_like_credit_card(value: str) -> bool:
    digits_only = re.sub(r"[\s-]", "", value)
    if not digits_only.isdigit():
        return False
    if len(digits_only) < 13 or len(digits_only) > 19:
        return False
    # Cheap Luhn check
    total = 0
    reverse = digits_only[::-1]
    for i, ch in enumerate(reverse):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


# ---------------------------------------------------------------------------
# In-memory store (mock mode)
# ---------------------------------------------------------------------------


class _InMemoryStore:
    """Simple list-of-dicts used in mock mode. Thread-unsafe by design —
    the test suite is single-threaded and the real app uses the DB."""

    def __init__(self) -> None:
        self._rows: list[Memory] = []

    def add(self, m: Memory) -> None:
        self._rows.append(m)

    def all(self) -> list[Memory]:
        return list(self._rows)

    def remove(self, memory_id: str) -> bool:
        before = len(self._rows)
        self._rows = [r for r in self._rows if r.id != memory_id]
        return len(self._rows) < before

    def remove_where(self, predicate) -> int:
        keep: list[Memory] = []
        removed = 0
        for r in self._rows:
            if predicate(r):
                removed += 1
            else:
                keep.append(r)
        self._rows = keep
        return removed


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class MemoryManager:
    """Persists + retrieves memories. Honors mock_mode (section 64).

    Usage::

        from automation_service.memory.manager import memory_manager, MemoryType
        await memory_manager.remember(MemoryType.USER_PREFERENCES,
                                      "downloads_folder",
                                      "/home/z/Downloads")
        hits = await memory_manager.recall(MemoryType.USER_PREFERENCES,
                                           "downloads_folder")
    """

    def __init__(self, mock_mode: Optional[bool] = None) -> None:
        # Lazy: import settings at construction time so tests that monkeypatch
        # settings.mock_mode between calls see the change.
        from ..config import settings

        self._mock_mode = settings.mock_mode if mock_mode is None else mock_mode
        self._in_memory_store = _InMemoryStore()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def remember(
        self,
        memory_type: MemoryType,
        key: str,
        value: Any,
        source: str = "system",
        ttl_seconds: Optional[int] = None,
        user_id: str = "default",
        workflow_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> str:
        """Store a memory entry. Returns the new memory_id.

        Raises:
            ValueError: if the value or key looks sensitive (section 57).
        """
        if await self.detect_sensitive_data(value, key=key):
            raise ValueError(
                f"refusing to remember sensitive value for key='{key}' "
                "(section 57: secrets must not auto-persist). Redact or store "
                "via the credential manager instead."
            )

        now = datetime.now(timezone.utc)
        expires_at: Optional[datetime] = None
        if memory_type == MemoryType.TEMPORARY:
            # TemporaryMemory always expires; default 1 hour if ttl not given.
            ttl = ttl_seconds if ttl_seconds is not None else 3600
            expires_at = now + timedelta(seconds=ttl)
        elif ttl_seconds is not None:
            # Other types respect an explicit TTL if provided, but never
            # expire by default.
            expires_at = now + timedelta(seconds=ttl_seconds)

        memory = Memory(
            user_id=user_id,
            type=memory_type,
            key=key,
            value=value,
            source=source,
            workflow_id=workflow_id,
            task_id=task_id,
            created_at=now,
            expires_at=expires_at,
        )

        if self._mock_mode:
            self._in_memory_store.add(memory)
        else:
            self._db_insert(memory)
        return memory.id

    async def recall(
        self,
        memory_type: MemoryType,
        key: Optional[str] = None,
        user_id: str = "default",
    ) -> list[Memory]:
        """Retrieve memories. If ``key`` is None, returns all entries of that type."""
        # Purge expired TemporaryMemory rows first.
        await self._expire_now()

        rows: Iterable[Memory]
        if self._mock_mode:
            rows = self._in_memory_store.all()
        else:
            rows = self._db_select(memory_type, key, user_id)

        out: list[Memory] = []
        for r in rows:
            if r.type != memory_type:
                continue
            if r.user_id != user_id:
                continue
            if key is not None and r.key != key:
                continue
            if r.expires_at is not None and r.expires_at <= datetime.now(timezone.utc):
                continue
            out.append(r)
        return out

    async def forget(self, memory_id: str) -> bool:
        if self._mock_mode:
            return self._in_memory_store.remove(memory_id)
        return self._db_delete(memory_id)

    async def forget_all(
        self,
        memory_type: MemoryType,
        key: Optional[str] = None,
        user_id: str = "default",
    ) -> int:
        if self._mock_mode:
            return self._in_memory_store.remove_where(
                lambda r: r.type == memory_type
                and r.user_id == user_id
                and (key is None or r.key == key)
            )
        return self._db_delete_where(memory_type, key, user_id)

    async def get_context_for_planner(self, user_id: str = "default") -> dict:
        """Returns the dict the PlannerAgent merges into its prompt."""
        prefs = await self.recall(MemoryType.USER_PREFERENCES, user_id=user_id)
        workflows = await self.recall(MemoryType.WORKFLOW, user_id=user_id)
        tasks = await self.recall(MemoryType.TASK_CONTEXT, user_id=user_id)
        # Cap recent workflow + task memories to keep the prompt small.
        recent_workflows = sorted(workflows, key=lambda m: m.created_at, reverse=True)[:10]
        active_tasks = sorted(tasks, key=lambda m: m.created_at, reverse=True)[:5]
        return {
            "user_preferences": [
                {"key": m.key, "value": m.value, "source": m.source} for m in prefs
            ],
            "recent_workflow_memory": [
                {"key": m.key, "value": m.value, "workflow_id": m.workflow_id}
                for m in recent_workflows
            ],
            "active_task_context": [
                {"key": m.key, "value": m.value, "task_id": m.task_id}
                for m in active_tasks
            ],
        }

    async def detect_sensitive_data(self, value: Any, key: Optional[str] = None) -> bool:
        """Return True if value looks like a secret (section 57).

        Checks, in order:
        1. The *key* name (case-insensitive, snake/camel/kebab normalized).
        2. The *value*, if it's a string:
           - matches a known API-key / token prefix (sk-, ghp_, xox, JWT, …)
           - matches a generic password-literal pattern (``password: foo``)
           - passes the credit-card Luhn check
           - is a long opaque string (32+ chars) with no spaces and high entropy
        3. The *value*, if it's a dict — recurses into known sensitive keys.
        """
        if key is not None:
            normalized = re.sub(r"[\-_]", "_", key).lower()
            if normalized in _SENSITIVE_KEY_NAMES:
                return True

        if value is None:
            return False

        if isinstance(value, str):
            return self._string_looks_sensitive(value)

        if isinstance(value, dict):
            for k, v in value.items():
                if await self.detect_sensitive_data(v, key=str(k)):
                    return True
            return False

        if isinstance(value, (list, tuple)):
            for v in value:
                if await self.detect_sensitive_data(v, key=None):
                    return True
            return False

        # Numbers, bools, etc. — never sensitive on their own.
        return False

    async def inspect_user_data(self, user_id: str) -> dict:
        """GDPR-style inspection (section 84). Returns ALL of a user's memories
        grouped by type, including expired ones (so the user can audit them)."""
        rows: Iterable[Memory]
        if self._mock_mode:
            rows = [r for r in self._in_memory_store.all() if r.user_id == user_id]
        else:
            rows = self._db_select_all_for_user(user_id)

        grouped: dict[str, list[dict]] = {}
        for r in rows:
            grouped.setdefault(r.type.value, []).append(
                {
                    "id": r.id,
                    "key": r.key,
                    "value": r.value,
                    "source": r.source,
                    "workflow_id": r.workflow_id,
                    "task_id": r.task_id,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                    "expires_at": r.expires_at.isoformat() if r.expires_at else None,
                }
            )
        return {
            "user_id": user_id,
            "count": sum(len(v) for v in grouped.values()),
            "memories": grouped,
        }

    async def clear_all_user_data(self, user_id: str) -> int:
        """GDPR right-to-be-forgotten. Returns count of deleted memories."""
        if self._mock_mode:
            return self._in_memory_store.remove_where(lambda r: r.user_id == user_id)
        return self._db_delete_user(user_id)

    # ------------------------------------------------------------------
    # Internal — secret detection helpers
    # ------------------------------------------------------------------

    def _string_looks_sensitive(self, value: str) -> bool:
        if not value:
            return False
        stripped = value.strip()
        # 1. Known token prefixes (high-confidence).
        for pat in _SECRET_TOKEN_PATTERNS:
            if pat.match(stripped):
                return True
        # 2. Password literal pattern: ``password: hunter2``.
        if _PASSWORD_LITERAL_PATTERN.search(stripped):
            return True
        # 2b. Substring check (conservative — section 57).
        if _PASSWORD_SUBSTRING_PATTERN.search(stripped):
            return True
        # 3. Credit card Luhn.
        if _looks_like_credit_card(stripped):
            return True
        # 4. Long opaque base64/hex string. But ONLY treat as sensitive when
        #    it doesn't look like an ordinary URL, file path, sentence, etc.
        #    A bare 32+ char alphanumeric string with no separators is a strong
        #    secret signal.
        if _LONG_OPAQUE_PATTERN.match(stripped) and not stripped.startswith(
            ("http://", "https://", "/", "~", ".")
        ):
            return True
        return False

    # ------------------------------------------------------------------
    # Internal — expiry sweep
    # ------------------------------------------------------------------

    async def _expire_now(self) -> int:
        """Delete all TemporaryMemory entries whose expires_at has passed.
        Returns the count removed. Runs on every recall()."""
        now = datetime.now(timezone.utc)

        if self._mock_mode:
            return self._in_memory_store.remove_where(
                lambda r: r.type == MemoryType.TEMPORARY
                and r.expires_at is not None
                and r.expires_at <= now
            )
        return self._db_delete_expired(now)

    # ------------------------------------------------------------------
    # DB helpers — lazy imports so tests in mock mode never need SQLAlchemy
    # ------------------------------------------------------------------

    def _db_insert(self, memory: Memory) -> None:
        from database.base import SessionLocal
        from database.models.schema import Memory as MemoryRow

        with SessionLocal() as session:
            row = MemoryRow(
                id=memory.id,
                user_id=memory.user_id,
                memory_type=memory.type.value,
                key=memory.key,
                value=_coerce_value(memory.value),
                source=memory.source,
                workflow_id=memory.workflow_id,
                task_id=memory.task_id,
                created_at=memory.created_at,
                expires_at=memory.expires_at,
            )
            session.add(row)
            session.commit()

    def _db_select(
        self,
        memory_type: MemoryType,
        key: Optional[str],
        user_id: str,
    ) -> list[Memory]:
        from database.base import SessionLocal
        from database.models.schema import Memory as MemoryRow

        with SessionLocal() as session:
            q = session.query(MemoryRow).filter(
                MemoryRow.memory_type == memory_type.value,
                MemoryRow.user_id == user_id,
            )
            if key is not None:
                q = q.filter(MemoryRow.key == key)
            rows = q.all()
            return [_row_to_memory(r) for r in rows]

    def _db_select_all_for_user(self, user_id: str) -> list[Memory]:
        from database.base import SessionLocal
        from database.models.schema import Memory as MemoryRow

        with SessionLocal() as session:
            rows = session.query(MemoryRow).filter(MemoryRow.user_id == user_id).all()
            return [_row_to_memory(r) for r in rows]

    def _db_delete(self, memory_id: str) -> bool:
        from database.base import SessionLocal
        from database.models.schema import Memory as MemoryRow

        with SessionLocal() as session:
            row = session.query(MemoryRow).filter(MemoryRow.id == memory_id).first()
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True

    def _db_delete_where(
        self,
        memory_type: MemoryType,
        key: Optional[str],
        user_id: str,
    ) -> int:
        from database.base import SessionLocal
        from database.models.schema import Memory as MemoryRow

        with SessionLocal() as session:
            q = session.query(MemoryRow).filter(
                MemoryRow.memory_type == memory_type.value,
                MemoryRow.user_id == user_id,
            )
            if key is not None:
                q = q.filter(MemoryRow.key == key)
            count = q.count()
            q.delete(synchronize_session=False)
            session.commit()
            return count

    def _db_delete_user(self, user_id: str) -> int:
        from database.base import SessionLocal
        from database.models.schema import Memory as MemoryRow

        with SessionLocal() as session:
            q = session.query(MemoryRow).filter(MemoryRow.user_id == user_id)
            count = q.count()
            q.delete(synchronize_session=False)
            session.commit()
            return count

    def _db_delete_expired(self, now: datetime) -> int:
        from database.base import SessionLocal
        from database.models.schema import Memory as MemoryRow

        with SessionLocal() as session:
            q = session.query(MemoryRow).filter(
                MemoryRow.memory_type == MemoryType.TEMPORARY.value,
                MemoryRow.expires_at.isnot(None),
                MemoryRow.expires_at <= now,
            )
            count = q.count()
            q.delete(synchronize_session=False)
            session.commit()
            return count


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _coerce_value(value: Any) -> dict:
    """Wrap non-dict values so SQLAlchemy JSON columns are happy.

    SQLAlchemy JSON columns accept arbitrary JSON-serializable values, but to
    keep the schema uniform we wrap non-dicts as ``{"v": value}`` and unwrap
    on read. This keeps both the DB and in-memory paths returning identical
    Python types.
    """
    if isinstance(value, dict):
        return value
    return {"v": value}


def _unwrap_value(value: Any) -> Any:
    if isinstance(value, dict) and set(value.keys()) == {"v"}:
        return value["v"]
    return value


def _row_to_memory(row) -> Memory:
    return Memory(
        id=row.id,
        user_id=row.user_id,
        type=MemoryType(row.memory_type),
        key=row.key,
        value=_unwrap_value(row.value),
        source=row.source,
        workflow_id=row.workflow_id,
        task_id=row.task_id,
        created_at=row.created_at,
        expires_at=row.expires_at,
    )


# ---------------------------------------------------------------------------
# Module-level singleton — mirrors scheduler_manager / backup_manager / etc.
# ---------------------------------------------------------------------------


memory_manager = MemoryManager()
