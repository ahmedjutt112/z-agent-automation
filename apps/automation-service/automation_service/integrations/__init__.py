"""Integrations package — master prompt §54 (OAuth + Messaging integrations).

Submodules:
- oauth: OAuth provider abstraction (Google / GitHub / Facebook) + flow helpers.
- email_client: SMTP/IMAP client (stdlib smtplib + imaplib, no extra deps).
- whatsapp: WhatsApp Business API client (Cloud, v18.0).
- telegram: Telegram Bot API client.
- discord: Discord Bot API client.

All clients respect ``settings.mock_mode`` — when True they return simulated
responses without touching the network. Secrets are read from the credential
manager (``automation_service.security.credentials``); NEVER hardcode secrets.
"""
