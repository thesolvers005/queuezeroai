"""
Real email notifications for QueueZero, sent via the Resend API.

Design rules:
- RESEND_API_KEY and FROM_EMAIL come from the environment — never hardcoded.
- send_confirmation_email() NEVER raises. A booking must complete even if the
  email fails, so every failure path logs a warning and returns
  {"sent": False, "error": ...} instead.
- No module-level per-request state. The recipient is resolved from the
  request's form value (falling back to the PATIENT_EMAIL env var) via the pure
  resolve_recipient() helper and passed in explicitly, so concurrent bookings
  can never leak one patient's email/details into another's.
- The HTML is a self-contained appointment slip (inline styles, no external
  images) that mirrors the green confirmation card in the UI.
"""

import os
import logging

logger = logging.getLogger("queuezero.notifications")

try:
    import resend
except ImportError:  # SDK not installed — degrade gracefully, never crash
    resend = None


def resolve_recipient(form_email):
    """Recipient for confirmation emails: the per-request form value if present,
    else DEMO_EMAIL_OVERRIDE (forces every send to the sandbox-allowed address,
    for the hackathon demo), else the PATIENT_EMAIL env var, else None.

    Pure function — takes the request's email and returns a value. No globals,
    so it is safe under concurrent requests.
    """
    override = os.environ.get("DEMO_EMAIL_OVERRIDE", "").strip()
    if override:
        return override
    if isinstance(form_email, str) and form_email.strip():
        return form_email.strip()
    return os.environ.get("PATIENT_EMAIL", "").strip() or None


def _slip_row(label, value):
    return (
        '<tr>'
        f'<td style="padding:6px 16px 0 0;font-size:11px;font-weight:600;'
        f'letter-spacing:0.5px;text-transform:uppercase;color:#047857;">{label}</td>'
        f'<td style="padding:6px 0 0 0;font-size:14px;color:#022c22;">{value}</td>'
        '</tr>'
    )


def _build_email_html(doctor, hospital, date, time, est_wait):
    """Appointment slip matching the UI confirmation card (emerald palette)."""
    rows = [
        _slip_row("Doctor", doctor),
        _slip_row("Hospital", hospital),
        _slip_row("Date", date),
        _slip_row("Time", time),
    ]
    if est_wait is not None:
        rows.append(_slip_row("Est. wait", f"{est_wait} min"))

    return f"""\
<div style="margin:0;padding:24px;background-color:#f2f8f6;font-family:Arial,Helvetica,sans-serif;">
  <div style="max-width:480px;margin:0 auto;">
    <p style="margin:0 0 4px 0;font-size:18px;font-weight:700;color:#134e4a;">QueueZero</p>
    <p style="margin:0 0 16px 0;font-size:12px;color:#64748b;">Skip the queue. Let AI book it.</p>
    <div style="background-color:#ecfdf5;border:1px solid #6ee7b7;border-radius:12px;padding:20px;">
      <p style="margin:0 0 12px 0;font-size:15px;font-weight:700;color:#065f46;">
        &#10003; Appointment confirmed
      </p>
      <table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
        {''.join(rows)}
      </table>
    </div>
    <p style="margin:16px 0 0 0;font-size:12px;color:#64748b;">
      Please arrive 10 minutes early and carry a photo ID.
      This is an automated confirmation from QueueZero.
    </p>
  </div>
</div>"""


def send_confirmation_email(to_email, doctor, hospital, date, time, est_wait):
    """
    Send the appointment confirmation email. Returns:
      {"sent": True, "email_id": ...}            on success
      {"sent": False, "error": "<reason>"}       on ANY failure (never raises)
    """
    if resend is None:
        logger.warning("Resend SDK not installed (pip install resend); skipping email.")
        return {"sent": False, "error": "resend SDK not installed"}

    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    from_email = os.environ.get("FROM_EMAIL", "").strip()
    if not api_key or not from_email:
        logger.warning("RESEND_API_KEY / FROM_EMAIL not configured; skipping email.")
        return {"sent": False, "error": "RESEND_API_KEY or FROM_EMAIL not configured"}
    if not to_email:
        logger.warning("No recipient email available; skipping confirmation email.")
        return {"sent": False, "error": "no recipient email"}

    try:
        resend.api_key = api_key
        result = resend.Emails.send({
            "from": from_email,
            "to": [to_email],
            "subject": f"Appointment confirmed — {doctor}, {date} at {time}",
            "html": _build_email_html(doctor, hospital, date, time, est_wait),
        })
        email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", None)
        logger.info("Confirmation email sent to %s (id=%s)", to_email, email_id)
        return {"sent": True, "email_id": email_id}
    except Exception as exc:
        detail = getattr(exc, "response", None)
        body = getattr(detail, "text", None) or getattr(detail, "content", None) or str(exc)
        logger.warning("Confirmation email to %s failed: %s", to_email, body)
        return {"sent": False, "error": str(body)}
