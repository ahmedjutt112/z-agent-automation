"""SQLAlchemy ORM models — master prompt §27 (database tables).

All 22 tables required by the master prompt:
users, settings, ai_providers, ai_models, api_credentials, permissions, tools,
workflows, workflow_versions, workflow_nodes, workflow_runs, tasks, task_steps,
task_logs, screenshots, browser_sessions, scheduled_jobs, triggers, notifications,
automation_history, error_logs, audit_logs, device_profiles.

Master prompt §95 (Database Rules):
- Every model has id, created_at, updated_at
- Use UUIDs where appropriate
- Indexes on workflow_id, task_id, status, created_at, scheduled_at
"""
