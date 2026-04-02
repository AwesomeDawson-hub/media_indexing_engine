"""Email sending via AWS SES (boto3).

Sending is a no-op when EMAIL_FROM is not configured, so the app works
fine in dev/sandbox mode without any setup.
"""

import logging

from src.config import settings

logger = logging.getLogger(__name__)


def _ses_client():
    """Lazy-import boto3 and return an SES client."""
    import boto3
    return boto3.client("ses", region_name=settings.email.aws_region)


def send_password_reset(to_address: str, token: str) -> None:
    """Send a password reset email.

    Does nothing if EMAIL_FROM is not configured (dev / sandbox fallback).
    """
    from_address = settings.email.from_address
    if not from_address:
        logger.info("EMAIL_FROM not set — skipping password reset email to %s", to_address)
        return

    app_url = settings.email.app_url.rstrip("/")
    reset_link = f"{app_url}/reset-password?token={token}"

    subject = "Reset your Vyzindex password"
    body_text = (
        f"You requested a password reset for your Vyzindex account.\n\n"
        f"Click the link below to set a new password (expires in 2 hours):\n\n"
        f"{reset_link}\n\n"
        f"If you did not request this, you can safely ignore this email."
    )
    body_html = f"""<!DOCTYPE html>
<html>
<body style="font-family: sans-serif; max-width: 480px; margin: 40px auto; color: #222;">
  <h2 style="color: #1a1a2e;">Reset your password</h2>
  <p>You requested a password reset for your Vyzindex account.</p>
  <p>
    <a href="{reset_link}"
       style="display:inline-block;padding:12px 24px;background:#4f46e5;color:#fff;
              border-radius:6px;text-decoration:none;font-weight:600;">
      Reset password
    </a>
  </p>
  <p style="color:#666;font-size:0.85em;">
    This link expires in 2 hours. If you did not request a password reset,
    you can safely ignore this email.
  </p>
</body>
</html>"""

    try:
        client = _ses_client()
        client.send_email(
            Source=from_address,
            Destination={"ToAddresses": [to_address]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {
                    "Text": {"Data": body_text, "Charset": "UTF-8"},
                    "Html": {"Data": body_html, "Charset": "UTF-8"},
                },
            },
        )
        logger.info("Password reset email sent to %s", to_address)
    except Exception:
        logger.exception("Failed to send password reset email to %s", to_address)
        # Don't raise — the token is still valid; user can request again
