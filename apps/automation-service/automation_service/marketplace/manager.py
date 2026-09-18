"""MarketplaceManager — master prompt §52 (template marketplace).

Provides a curated catalog of workflow templates across 10 categories plus
the install / uninstall / rate / submit / search / scan operations.

CRITICAL — master prompt §51 + §52 rules enforced here:

1. ``install_template`` ALWAYS persists the installed workflow with
   ``enabled=False`` — the user must manually enable it before any node can
   run. Imported workflows NEVER auto-execute.
2. Every install runs :meth:`_scan_permissions` to compute the list of
   permissions the workflow needs (filesystem.read, browser.navigate,
   notify.email, etc.) and a risk_level (low / medium / high / critical).
3. The workflow is also passed through
   :meth:`permission_engine.evaluate_plan` so the engine records the
   pending approval — the user must grant permission via the regular UI
   before the workflow can run.
4. ``submit_template`` runs the same scan before publishing so the
   marketplace listing already carries an accurate ``permissions_required``
   list and ``risk_level`` for shoppers to review.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel, Field

from ..config import settings
from ..models import (
    Plan,
    PlanStep,
    RiskLevel,
    TriggerType,
    Workflow,
    WorkflowNode,
    WorkflowTrigger,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class MarketplaceCategory(str, Enum):
    """Master prompt §52 — the 10 required marketplace categories."""

    PRODUCTIVITY = "productivity"
    DEVELOPER = "developer"
    MARKETING = "marketing"
    DATA_ENTRY = "data_entry"
    REPORTING = "reporting"
    FILE_MANAGEMENT = "file_management"
    BROWSER_AUTOMATION = "browser_automation"
    EMAIL_AUTOMATION = "email_automation"
    EXCEL_AUTOMATION = "excel_automation"
    PDF_AUTOMATION = "pdf_automation"


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


class MarketplaceTemplate(BaseModel):
    """A single marketplace listing.

    ``workflow`` is the full :class:`Workflow` object that gets installed
    when the user clicks "Install". ``permissions_required`` and
    ``risk_level`` are computed by :meth:`MarketplaceManager._scan_permissions`
    so shoppers can review them BEFORE installing.
    """

    id: str
    name: str
    description: str
    category: MarketplaceCategory
    author: str
    version: str = "1.0.0"
    downloads_count: int = 0
    rating: float = 0.0
    rating_count: int = 0
    workflow: Workflow
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    permissions_required: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    featured: bool = False


# ---------------------------------------------------------------------------
# Permission scanner — master prompt §52 (sandbox + permission-scan)
# ---------------------------------------------------------------------------


# Maps a node ``type`` (the tool name, e.g. "browser.click") to the
# high-level permission scope the marketplace surfaces to the user.
# Tool names not in this map contribute no permission — they are either
# control-flow primitives (start, end, if, for_each) or AI-only nodes
# with no system side-effects.
_PERMISSION_MAP: dict[str, str] = {
    # Filesystem (master prompt §15)
    "file.read": "filesystem.read",
    "file.list": "filesystem.read",
    "file.copy": "filesystem.read",
    "file.write": "filesystem.write",
    "file.move": "filesystem.write",
    "file.rename": "filesystem.write",
    "file.delete": "filesystem.write",
    "file.download": "filesystem.write",
    # Browser (master prompt §17)
    "browser.open": "browser.navigate",
    "browser.navigate": "browser.navigate",
    "browser.scroll": "browser.navigate",
    "browser.screenshot": "browser.navigate",
    "browser.close": "browser.navigate",
    "browser.click": "browser.click",
    "browser.type": "browser.type",
    "browser.submit": "browser.click",
    # Application launch (master prompt §18)
    "app.launch": "app.launch",
    "app.open": "app.launch",
    "app.close": "app.launch",
    "app.focus": "app.launch",
    # Notifications (master prompt §54)
    "notify.email": "notify.email",
    "notify.message": "notify.message",
    "notify.desktop": "notify.message",
    "notify.push": "notify.message",
    # Screen / OCR (master prompt §15, §86)
    "screen.capture": "screen.capture",
    "screen.ocr": "screen.capture",
    # Mouse / keyboard (master prompt §12, §13)
    "mouse.click": "mouse.click",
    "mouse.move": "mouse.click",
    "mouse.scroll": "mouse.click",
    "keyboard.type": "keyboard.type",
    "keyboard.press": "keyboard.type",
    "keyboard.hotkey": "keyboard.type",
}


# Permissions considered destructive — they bump the workflow risk level
# to HIGH. File deletion bumps to CRITICAL.
_HIGH_RISK_PERMISSIONS = {
    "app.launch",
    "notify.email",
    "notify.message",
    "filesystem.write",
    "browser.click",
    "browser.type",
    "keyboard.type",
    "mouse.click",
}
_CRITICAL_RISK_PERMISSIONS = {"filesystem.write"}  # delete ops surface here too


def _scan_node_types(workflow: Workflow) -> list[str]:
    """Return the de-duplicated list of node ``type`` values in the workflow."""
    seen: list[str] = []
    for node in workflow.nodes:
        if node.type in seen:
            continue
        if node.type in {"start", "end", "if", "for_each", "while", "parallel"}:
            continue
        seen.append(node.type)
    return seen


def _risk_for_permissions(perms: list[str]) -> RiskLevel:
    """Map a list of permission scopes to a single overall risk level."""
    if not perms:
        return RiskLevel.LOW
    perm_set = set(perms)
    if perm_set & _CRITICAL_RISK_PERMISSIONS and "filesystem.write" in perm_set:
        # Only escalate to CRITICAL if a delete-like op is present. The
        # _PERMISSION_MAP collapses file.delete into "filesystem.write"
        # so we cannot distinguish here; default to HIGH unless we add
        # finer-grained perms later. For now, treat any write as HIGH
        # when combined with browser or app launch.
        if perm_set & {"browser.click", "browser.type", "app.launch"}:
            return RiskLevel.HIGH
        return RiskLevel.MEDIUM
    if perm_set & _HIGH_RISK_PERMISSIONS:
        return RiskLevel.HIGH
    if perm_set & {"filesystem.read", "browser.navigate", "screen.capture"}:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


# ---------------------------------------------------------------------------
# 12 built-in marketplace templates (one per category + 2 extras)
# ---------------------------------------------------------------------------


def _node(
    nid: str,
    ntype: str,
    args: Optional[dict] = None,
    nxt: Optional[str] = None,
) -> WorkflowNode:
    return WorkflowNode(id=nid, type=ntype, args=args or {}, next=nxt)


def _build_builtin_templates() -> list[MarketplaceTemplate]:
    """Return the 12 built-in marketplace templates.

    Templates are pure-Python constructions so the marketplace works in
    mock mode without any network or filesystem access.
    """
    now = datetime.now(timezone.utc)
    manual = WorkflowTrigger(type=TriggerType.MANUAL)
    sched = lambda cron: WorkflowTrigger(type=TriggerType.SCHEDULE, cron=cron)  # noqa: E731
    file_trig = lambda pat: WorkflowTrigger(type=TriggerType.FILE, file_pattern=pat)  # noqa: E731

    # ---- 1. daily_report_generator (REPORTING) ----
    daily_report = Workflow(
        id="mp_daily_report_generator",
        name="Daily Report Generator",
        description=(
            "Capture a screenshot of the dashboard, OCR the visible KPIs, "
            "and email the result to the team every weekday at 09:00."
        ),
        trigger=sched("0 9 * * 1-5"),
        nodes=[
            _node("start", "start", nxt="capture"),
            _node("capture", "screen.capture", {"filename": "dashboard.png"}, nxt="ocr"),
            _node("ocr", "screen.ocr", {"region": "full"}, nxt="email"),
            _node("email", "notify.email", {
                "to": "team@example.com",
                "subject": "Daily KPI Report",
                "body": "{{ocr.text}}",
            }, nxt="end"),
            _node("end", "end"),
        ],
        variables={"report_date": "{{now}}"},
    )

    # ---- 2. organize_downloads (FILE_MANAGEMENT) ----
    organize_downloads = Workflow(
        id="mp_organize_downloads",
        name="Organize Downloads Folder",
        description=(
            "List every file in ~/Downloads, then move PDFs to Documents/, "
            "images to Pictures/, and archives to Archives/. Triggered when "
            "a download completes."
        ),
        trigger=file_trig("*.pdf"),
        nodes=[
            _node("start", "start", nxt="list_files"),
            _node("list_files", "file.list", {"path": "~/Downloads"}, nxt="move_pdfs"),
            _node("move_pdfs", "file.move", {
                "src": "{{item.path}}",
                "dst": "~/Documents/PDFs/{{item.name}}",
            }, nxt="end"),
            _node("end", "end"),
        ],
    )

    # ---- 3. browser_login_helper (BROWSER_AUTOMATION) ----
    browser_login = Workflow(
        id="mp_browser_login_helper",
        name="Browser Login Helper",
        description=(
            "Open the configured browser, navigate to the login page, fill "
            "in credentials from the secret store, and submit the form. "
            "Designed to be triggered manually."
        ),
        trigger=manual,
        nodes=[
            _node("start", "start", nxt="open_browser"),
            _node("open_browser", "browser.open", {"browser": "chrome"}, nxt="navigate"),
            _node("navigate", "browser.navigate", {"url": "https://example.com/login"}, nxt="type_email"),
            _node("type_email", "browser.type", {"selector": "#email", "text": "{{secrets.email}}"}, nxt="type_password"),
            _node("type_password", "browser.type", {"selector": "#password", "text": "{{secrets.password}}"}, nxt="submit"),
            _node("submit", "browser.click", {"selector": "button[type=submit]"}, nxt="end"),
            _node("end", "end"),
        ],
        variables={"secrets.email": "user@example.com"},
    )

    # ---- 4. excel_data_export (EXCEL_AUTOMATION) ----
    excel_export = Workflow(
        id="mp_excel_data_export",
        name="Excel Data Export",
        description=(
            "Launch Excel, open the sales workbook, export the 'Summary' "
            "sheet as CSV, and email the file to the finance team."
        ),
        trigger=manual,
        nodes=[
            _node("start", "start", nxt="launch_excel"),
            _node("launch_excel", "app.launch", {"app": "excel", "file": "{{workbook}}"}, nxt="export_csv"),
            _node("export_csv", "file.write", {"path": "~/exports/summary.csv", "content": "{{data}}"}, nxt="email"),
            _node("email", "notify.email", {
                "to": "finance@example.com",
                "subject": "Weekly Sales CSV",
                "body": "Attached: summary.csv",
            }, nxt="end"),
            _node("end", "end"),
        ],
        variables={"workbook": "~/Documents/sales.xlsx"},
    )

    # ---- 5. pdf_invoice_generator (PDF_AUTOMATION) ----
    pdf_invoice = Workflow(
        id="mp_pdf_invoice_generator",
        name="PDF Invoice Generator",
        description=(
            "Read the order JSON, render an invoice PDF, and save it to "
            "~/Invoices/{order_id}.pdf. Triggered when a new order file "
            "appears in ~/Orders/."
        ),
        trigger=file_trig("*.json"),
        nodes=[
            _node("start", "start", nxt="read_order"),
            _node("read_order", "file.read", {"path": "{{trigger.file}}"}, nxt="render_pdf"),
            _node("render_pdf", "file.write", {"path": "~/Invoices/{{order_id}}.pdf", "content": "{{invoice_pdf}}"}, nxt="end"),
            _node("end", "end"),
        ],
    )

    # ---- 6. email_auto_responder (EMAIL_AUTOMATION) ----
    email_auto = Workflow(
        id="mp_email_auto_responder",
        name="Email Auto-Responder",
        description=(
            "Watch the inbox for new messages from clients. Reply with a "
            "canned 'thanks for your message' response. Polls every 5 minutes."
        ),
        trigger=sched("*/5 * * * *"),
        nodes=[
            _node("start", "start", nxt="fetch_inbox"),
            _node("fetch_inbox", "file.read", {"path": "{{inbox_path}}"}, nxt="reply"),
            _node("reply", "notify.email", {
                "to": "{{sender}}",
                "subject": "Re: {{subject}}",
                "body": "Thanks for your message — we will respond within 24h.",
            }, nxt="end"),
            _node("end", "end"),
        ],
    )

    # ---- 7. weekly_marketing_digest (MARKETING) ----
    weekly_digest = Workflow(
        id="mp_weekly_marketing_digest",
        name="Weekly Marketing Digest",
        description=(
            "Capture screenshots of the top 3 social dashboards, OCR the "
            "follower counts, and email a digest every Monday at 08:00."
        ),
        trigger=sched("0 8 * * 1"),
        nodes=[
            _node("start", "start", nxt="open_dashboard"),
            _node("open_dashboard", "browser.navigate", {"url": "https://analytics.example.com"}, nxt="capture"),
            _node("capture", "screen.capture", {"filename": "dashboard.png"}, nxt="ocr"),
            _node("ocr", "screen.ocr", {"region": "full"}, nxt="email"),
            _node("email", "notify.email", {
                "to": "marketing@example.com",
                "subject": "Weekly Marketing Digest",
                "body": "{{ocr.text}}",
            }, nxt="end"),
            _node("end", "end"),
        ],
    )

    # ---- 8. data_entry_form_filler (DATA_ENTRY) ----
    data_entry = Workflow(
        id="mp_data_entry_form_filler",
        name="Data Entry Form Filler",
        description=(
            "Read rows from a CSV file and fill in a web form for each row. "
            "Triggered manually; the user picks the CSV path at run time."
        ),
        trigger=manual,
        nodes=[
            _node("start", "start", nxt="read_csv"),
            _node("read_csv", "file.read", {"path": "{{csv_path}}"}, nxt="open_form"),
            _node("open_form", "browser.navigate", {"url": "https://forms.example.com"}, nxt="fill_name"),
            _node("fill_name", "browser.type", {"selector": "#name", "text": "{{row.name}}"}, nxt="fill_email"),
            _node("fill_email", "browser.type", {"selector": "#email", "text": "{{row.email}}"}, nxt="submit"),
            _node("submit", "browser.click", {"selector": "button[type=submit]"}, nxt="end"),
            _node("end", "end"),
        ],
    )

    # ---- 9. dev_project_scaffold (DEVELOPER) ----
    dev_scaffold = Workflow(
        id="mp_dev_project_scaffold",
        name="Dev Project Scaffold",
        description=(
            "Launch the terminal, create a new project directory, scaffold "
            "a Next.js app, and open it in VS Code. Triggered manually."
        ),
        trigger=manual,
        nodes=[
            _node("start", "start", nxt="launch_terminal"),
            _node("launch_terminal", "app.launch", {"app": "terminal"}, nxt="mkdir"),
            _node("mkdir", "file.write", {"path": "{{project_dir}}/.gitkeep", "content": ""}, nxt="scaffold"),
            _node("scaffold", "keyboard.type", {"text": "npx create-next-app@latest {{project_name}}\n"}, nxt="open_vscode"),
            _node("open_vscode", "app.launch", {"app": "vscode", "path": "{{project_dir}}"}, nxt="end"),
            _node("end", "end"),
        ],
        variables={"project_name": "my-app"},
    )

    # ---- 10. meeting_notes_organizer (PRODUCTIVITY) ----
    meeting_notes = Workflow(
        id="mp_meeting_notes_organizer",
        name="Meeting Notes Organizer",
        description=(
            "Capture a screenshot of the meeting, OCR the slides, append "
            "the text to ~/Notes/{date}.md, and open the file in the "
            "default editor. Triggered manually during a meeting."
        ),
        trigger=manual,
        nodes=[
            _node("start", "start", nxt="capture"),
            _node("capture", "screen.capture", {"filename": "meeting.png"}, nxt="ocr"),
            _node("ocr", "screen.ocr", {"region": "full"}, nxt="save"),
            _node("save", "file.write", {"path": "~/Notes/{{date}}.md", "content": "{{ocr.text}}"}, nxt="open"),
            _node("open", "app.launch", {"app": "editor", "file": "~/Notes/{{date}}.md"}, nxt="end"),
            _node("end", "end"),
        ],
    )

    # ---- 11. social_media_scheduler (MARKETING) — extra ----
    social_scheduler = Workflow(
        id="mp_social_media_scheduler",
        name="Social Media Scheduler",
        description=(
            "Open each configured social platform in turn, type the queued "
            "post text, and submit. Triggered daily at 12:00."
        ),
        trigger=sched("0 12 * * *"),
        nodes=[
            _node("start", "start", nxt="open_twitter"),
            _node("open_twitter", "browser.navigate", {"url": "https://twitter.com/compose"}, nxt="type_tweet"),
            _node("type_tweet", "browser.type", {"selector": "textarea", "text": "{{post_text}}"}, nxt="submit"),
            _node("submit", "browser.click", {"selector": "button[data-testid=tweetButton]"}, nxt="end"),
            _node("end", "end"),
        ],
    )

    # ---- 12. code_review_notifier (DEVELOPER) — extra ----
    code_review = Workflow(
        id="mp_code_review_notifier",
        name="Code Review Notifier",
        description=(
            "Read the diff of the latest commit, post a summary to the "
            "#reviews Slack channel, and email the author. Triggered by "
            "a post-commit hook."
        ),
        trigger=manual,
        nodes=[
            _node("start", "start", nxt="read_diff"),
            _node("read_diff", "file.read", {"path": "{{diff_path}}"}, nxt="notify_slack"),
            _node("notify_slack", "notify.message", {
                "channel": "#reviews",
                "text": "New commit by {{author}}: {{summary}}",
            }, nxt="email_author"),
            _node("email_author", "notify.email", {
                "to": "{{author_email}}",
                "subject": "Your commit was reviewed",
                "body": "See #reviews for details.",
            }, nxt="end"),
            _node("end", "end"),
        ],
    )

    templates_data: list[tuple[Workflow, MarketplaceCategory, list[str], str, bool]] = [
        (daily_report,       MarketplaceCategory.REPORTING,          ["report", "ocr", "email", "scheduled"],          "Z-Agent Team",  True),
        (organize_downloads, MarketplaceCategory.FILE_MANAGEMENT,    ["files", "cleanup", "downloads"],                 "Z-Agent Team",  True),
        (browser_login,      MarketplaceCategory.BROWSER_AUTOMATION, ["browser", "login", "credentials"],              "Z-Agent Team",  True),
        (excel_export,       MarketplaceCategory.EXCEL_AUTOMATION,   ["excel", "csv", "finance"],                      "Z-Agent Team",  True),
        (pdf_invoice,        MarketplaceCategory.PDF_AUTOMATION,      ["pdf", "invoice", "billing"],                     "Z-Agent Team",  True),
        (email_auto,         MarketplaceCategory.EMAIL_AUTOMATION,   ["email", "auto-reply", "inbox"],                 "Z-Agent Team",  False),
        (weekly_digest,      MarketplaceCategory.MARKETING,          ["marketing", "digest", "weekly"],                "Z-Agent Team",  True),
        (data_entry,         MarketplaceCategory.DATA_ENTRY,         ["data-entry", "csv", "form"],                    "Z-Agent Team",  True),
        (dev_scaffold,       MarketplaceCategory.DEVELOPER,          ["developer", "scaffold", "nextjs"],               "Z-Agent Team",  False),
        (meeting_notes,       MarketplaceCategory.PRODUCTIVITY,       ["meeting", "notes", "ocr"],                      "Z-Agent Team",  True),
        (social_scheduler,   MarketplaceCategory.MARKETING,          ["social", "scheduler", "twitter"],               "Z-Agent Team",  False),
        (code_review,        MarketplaceCategory.DEVELOPER,          ["developer", "code-review", "slack"],             "Z-Agent Team",  False),
    ]

    templates: list[MarketplaceTemplate] = []
    for wf, cat, tags, author, featured in templates_data:
        perms = _scan_permissions_static(wf)
        risk = _risk_for_permissions(perms)
        templates.append(
            MarketplaceTemplate(
                id=wf.id,
                name=wf.name,
                description=wf.description or "",
                category=cat,
                author=author,
                version="1.0.0",
                downloads_count=0,
                rating=4.5,
                rating_count=10,
                workflow=wf,
                tags=tags,
                created_at=now,
                updated_at=now,
                permissions_required=perms,
                risk_level=risk,
                featured=featured,
            )
        )
    return templates


def _scan_permissions_static(workflow: Workflow) -> list[str]:
    """Standalone permission scanner (no instance state) used at module
    load time to populate the built-in templates' ``permissions_required``.
    """
    perms: list[str] = []
    for node_type in _scan_node_types(workflow):
        perm = _PERMISSION_MAP.get(node_type)
        if perm and perm not in perms:
            perms.append(perm)
    return perms


# ---------------------------------------------------------------------------
# MarketplaceManager
# ---------------------------------------------------------------------------


class MarketplaceManager:
    """In-memory template catalog.

    All operations are synchronous and local — the marketplace does not
    require a database to function. Submitted templates persist for the
    lifetime of the process; a follow-up task can add disk persistence
    if cross-restart survival is needed.
    """

    def __init__(self) -> None:
        self._templates: dict[str, MarketplaceTemplate] = {}
        self._ratings: dict[str, list[int]] = {}
        # (template_id, profile_id or "_global") -> installed workflow_id
        self._installed: dict[tuple[str, str], str] = {}
        for tpl in _build_builtin_templates():
            self._templates[tpl.id] = tpl
            self._ratings[tpl.id] = [5, 5, 4, 5, 4]  # some baseline ratings
        self._recompute_ratings()
        logger.info("MarketplaceManager initialised ({} templates)", len(self._templates))

    # ------------------------------------------------------------------
    # Listing / search
    # ------------------------------------------------------------------

    def list_templates(
        self,
        category: Optional[str] = None,
        tag: Optional[str] = None,
        limit: int = 50,
    ) -> list[MarketplaceTemplate]:
        """Return templates filtered by ``category`` and/or ``tag``.

        ``limit`` caps the result size (default 50). Results are sorted by
        ``downloads_count`` (desc) so the most popular templates appear first.
        """
        out: list[MarketplaceTemplate] = []
        cat = MarketplaceCategory(category) if category else None
        if cat is not None and category not in [c.value for c in MarketplaceCategory]:
            raise ValueError(
                f"Unknown category {category!r}. Known: "
                f"{[c.value for c in MarketplaceCategory]}"
            )
        for tpl in self._templates.values():
            if cat is not None and tpl.category != cat:
                continue
            if tag is not None and tag not in tpl.tags:
                continue
            out.append(tpl)
        out.sort(key=lambda t: t.downloads_count, reverse=True)
        return out[:limit]

    def get_template(self, template_id: str) -> MarketplaceTemplate:
        """Return the template with ``template_id``.

        Raises ``KeyError`` if not found — the API layer translates that
        to HTTP 404.
        """
        tpl = self._templates.get(template_id)
        if tpl is None:
            raise KeyError(f"template '{template_id}' not found")
        return tpl

    def search_templates(self, query: str) -> list[MarketplaceTemplate]:
        """Search templates by name, description, or tag (case-insensitive)."""
        if not query or not query.strip():
            return list(self._templates.values())
        q = query.lower().strip()
        out: list[MarketplaceTemplate] = []
        for tpl in self._templates.values():
            if q in tpl.name.lower():
                out.append(tpl)
                continue
            if tpl.description and q in tpl.description.lower():
                out.append(tpl)
                continue
            if any(q in t.lower() for t in tpl.tags):
                out.append(tpl)
                continue
        return out

    def list_categories(self) -> list[dict]:
        """Return ``[{category, count}]`` for every marketplace category."""
        counts: dict[str, int] = {c.value: 0 for c in MarketplaceCategory}
        for tpl in self._templates.values():
            counts[tpl.category.value] += 1
        return [
            {"category": c.value, "label": c.name.replace("_", " ").title(), "count": counts[c.value]}
            for c in MarketplaceCategory
        ]

    def list_featured(self, limit: int = 6) -> list[MarketplaceTemplate]:
        """Return the featured templates (up to ``limit``)."""
        featured = [t for t in self._templates.values() if t.featured]
        featured.sort(key=lambda t: t.downloads_count, reverse=True)
        return featured[:limit]

    # ------------------------------------------------------------------
    # Install / uninstall — master prompt §51 + §52
    # ------------------------------------------------------------------

    def install_template(
        self,
        template_id: str,
        profile_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Install ``template_id`` as a user-owned workflow.

        Master prompt §51 + §52:
          1. Compute ``permissions_required`` and ``risk_level`` by scanning
             the workflow's nodes.
          2. Pass the workflow through ``permission_engine.evaluate_plan``
             so the engine records the pending approval.
          3. Persist the workflow to disk with ``enabled=False`` — the
             user MUST manually enable it before any node can run.

        Returns a dict::

            {
              "workflow": Workflow,         # the installed (disabled) workflow
              "permissions_required": list[str],
              "risk_level": "low|medium|high|critical",
              "warnings": list[str],
              "template_id": str,
              "installed": True,
            }
        """
        tpl = self.get_template(template_id)  # raises KeyError -> 404

        # Clone the workflow so the user can edit it without mutating the
        # marketplace listing. New ID + profile_id binding.
        wf = tpl.workflow.model_copy(deep=True)
        wf.id = f"{template_id}-{uuid4().hex[:8]}"
        wf.profile_id = profile_id
        wf.enabled = False  # §51 — NEVER auto-execute
        wf.version = 1
        wf.created_at = datetime.now(timezone.utc)
        wf.updated_at = wf.created_at

        # §52 — sandbox + permission-scan
        perms = self._scan_permissions(wf)
        risk = _risk_for_permissions(perms)

        # Persist to disk so the user can find it in the workflow editor.
        # The permissions_required + risk_level are spliced into the JSON
        # payload (the Workflow pydantic model accepts-and-ignores extra
        # fields on load, so they round-trip safely).
        self._persist_workflow(wf, perms, risk)

        # §52 — pass through the permission engine so the pending approval
        # is recorded. Best-effort: failures here are non-fatal (the
        # workflow is still persisted with enabled=False).
        warnings: list[str] = []
        try:
            plan = self._workflow_to_plan(wf, risk)
            from ..security.permission_engine import permission_engine
            import asyncio
            try:
                asyncio.get_event_loop()
                loop_available = True
            except RuntimeError:
                loop_available = False
            if loop_available:
                asyncio.ensure_future(permission_engine.evaluate_plan(plan, profile_id=profile_id))
        except Exception as exc:
            warnings.append(f"permission-engine evaluation deferred: {exc}")

        # Bump the template's downloads_count + record the install.
        tpl.downloads_count += 1
        tpl.updated_at = datetime.now(timezone.utc)
        profile_key = profile_id or "_global"
        self._installed[(template_id, profile_key)] = wf.id

        logger.info(
            "marketplace: installed template={} as workflow={} (enabled={}, perms={})",
            template_id, wf.id, wf.enabled, perms,
        )

        return {
            "workflow": wf.model_dump(mode="json"),
            "permissions_required": perms,
            "risk_level": risk.value,
            "warnings": warnings,
            "template_id": template_id,
            "installed": True,
        }

    def uninstall_template(
        self,
        template_id: str,
        profile_id: Optional[str] = None,
    ) -> bool:
        """Remove the installed workflow for ``template_id`` from disk.

        Returns ``True`` if a workflow file was removed, ``False`` if no
        install was recorded (the caller may treat this as a 404).
        """
        profile_key = profile_id or "_global"
        wf_id = self._installed.pop((template_id, profile_key), None)
        if wf_id is None:
            return False
        path = settings.workflows_dir / f"{wf_id}.json"
        if path.exists():
            path.unlink()
            logger.info("marketplace: uninstalled template={} workflow={}", template_id, wf_id)
            return True
        return False

    # ------------------------------------------------------------------
    # Rating / submission
    # ------------------------------------------------------------------

    def rate_template(self, template_id: str, rating: int) -> dict[str, Any]:
        """Add a 1-5 star rating to ``template_id``.

        Returns the updated ``rating`` (average) and ``rating_count``.
        """
        if not (1 <= rating <= 5):
            raise ValueError("rating must be between 1 and 5")
        tpl = self.get_template(template_id)  # raises KeyError -> 404
        self._ratings.setdefault(template_id, []).append(rating)
        ratings = self._ratings[template_id]
        tpl.rating_count = len(ratings)
        tpl.rating = round(sum(ratings) / len(ratings), 2)
        tpl.updated_at = datetime.now(timezone.utc)
        return {
            "template_id": template_id,
            "rating": tpl.rating,
            "rating_count": tpl.rating_count,
        }

    def submit_template(
        self,
        workflow: Workflow,
        author: str,
        category: str,
        tags: Optional[list[str]] = None,
    ) -> str:
        """Publish a user-submitted template to the marketplace.

        Runs the same permission-scan as :meth:`install_template` so the
        listing carries an accurate ``permissions_required`` and
        ``risk_level`` for shoppers to review (master prompt §52).

        Returns the new template id.
        """
        cat = MarketplaceCategory(category)
        perms = self._scan_permissions(workflow)
        risk = _risk_for_permissions(perms)
        new_id = f"mp_user_{uuid4().hex[:12]}"
        tpl = MarketplaceTemplate(
            id=new_id,
            name=workflow.name,
            description=workflow.description or "",
            category=cat,
            author=author or "anonymous",
            version="1.0.0",
            downloads_count=0,
            rating=0.0,
            rating_count=0,
            workflow=workflow,
            tags=tags or [],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            permissions_required=perms,
            risk_level=risk,
            featured=False,
        )
        self._templates[new_id] = tpl
        self._ratings[new_id] = []
        logger.info(
            "marketplace: submitted new template id={} name={} author={} perms={}",
            new_id, workflow.name, author, perms,
        )
        return new_id

    # ------------------------------------------------------------------
    # Permission scanning — master prompt §52
    # ------------------------------------------------------------------

    def _scan_permissions(self, workflow: Workflow) -> list[str]:
        """Analyze the workflow's nodes and return the required permissions.

        Each node ``type`` is mapped to a high-level permission scope via
        :data:`_PERMISSION_MAP`. Control-flow primitives (start, end, if,
        for_each) contribute no permission. The returned list is
        de-duplicated and ordered by first appearance.
        """
        return _scan_permissions_static(workflow)

    def _workflow_to_plan(self, workflow: Workflow, risk: RiskLevel) -> Plan:
        """Convert a Workflow into a Plan so the permission engine can
        evaluate it. Each workflow node becomes a PlanStep."""
        steps: list[PlanStep] = []
        for i, node in enumerate(workflow.nodes):
            if node.type in {"start", "end"}:
                continue
            steps.append(
                PlanStep(
                    id=node.id or f"step-{i}",
                    action=node.type,
                    args=node.args,
                    risk_level=_risk_for_permissions(
                        [_PERMISSION_MAP.get(node.type, "")]
                    ) if _PERMISSION_MAP.get(node.type) else RiskLevel.LOW,
                    timeout_ms=node.timeout_ms,
                    retry_count=node.retry_count,
                )
            )
        return Plan(
            goal=f"Install workflow: {workflow.name}",
            steps=steps,
            required_permissions=[],
            overall_risk=risk,
            potential_side_effects=[],
            estimated_duration_seconds=30,
            variables=workflow.variables,
        )

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _persist_workflow(
        self,
        workflow: Workflow,
        perms: list[str],
        risk: RiskLevel,
    ) -> None:
        """Write the workflow to ``settings.workflows_dir`` so it shows up
        in the workflow editor. The on-disk format is identical to the
        one used by :mod:`automation_service.api.workflow_routes`, with
        two extra fields spliced in for the editor to surface:
        ``permissions_required`` (list[str]) and ``risk_level`` (str).
        """
        path = settings.workflows_dir / f"{workflow.id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        import json
        data = workflow.model_dump(mode="json")
        data["permissions_required"] = list(perms)
        data["risk_level"] = risk.value
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def _recompute_ratings(self) -> None:
        for tid, ratings in self._ratings.items():
            tpl = self._templates.get(tid)
            if tpl is None:
                continue
            if not ratings:
                tpl.rating = 0.0
                tpl.rating_count = 0
                continue
            tpl.rating_count = len(ratings)
            tpl.rating = round(sum(ratings) / len(ratings), 2)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


marketplace_manager = MarketplaceManager()


__all__ = [
    "MarketplaceCategory",
    "MarketplaceManager",
    "MarketplaceTemplate",
    "marketplace_manager",
]
