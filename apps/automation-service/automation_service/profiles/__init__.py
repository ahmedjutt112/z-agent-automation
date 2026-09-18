"""Multi-profile support — master prompt section 49.

Each profile is a sandboxed slice of: workflows, permissions, browser sessions,
AI provider config, variables, integrations. The active profile determines which
slice the planner / executor operates on.

In mock mode the profile store is in-memory. Otherwise it persists to the
``device_profiles`` table (already defined in database/models/schema.py).
"""
