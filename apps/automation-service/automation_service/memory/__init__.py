"""AI Memory subsystem — master prompt section 84.

Five memory types:
- UserPreferences  (persists forever)
- WorkflowMemory    (tied to a workflow_id)
- ApplicationMemory (per-app behavioral facts)
- TaskContext       (tied to a task_id)
- TemporaryMemory   (expires after ttl_seconds)

CRITICAL (section 57): secrets are never auto-persisted. ``detect_sensitive_data``
refuses to remember anything that looks like a password / API key / token / credit
card number — the caller must explicitly redact first.
"""
