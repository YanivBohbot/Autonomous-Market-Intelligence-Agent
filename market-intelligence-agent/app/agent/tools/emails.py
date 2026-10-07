"""send_email tool — Amazon SES via boto3.

Replaces the previous smtplib path. SES is the AWS-native fit:
- No SMTP port/SSL mismatch ambiguity.
- No App Password / 2FA bookkeeping in Secrets Manager.
- IAM-scoped to the runtime role, with the ses:SendEmail action limited
  to the specific verified sender identity ARN.
- Sandbox-mode caveat: the recipient must also be a verified SES
  identity until production access is requested. For the v1 demo we
  self-send (sender == recipient), which is always allowed.

Simulation gate stays for local dev where EMAIL_SENDER is empty or a
placeholder — the tool returns a fake-success string and never calls SES.
"""

from __future__ import annotations

import logging
import mimetypes
import os
from email.message import EmailMessage

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.report_catalog import resolve_generated_report
from app.core.config import settings

logger = logging.getLogger(__name__)

MAX_RAW_EMAIL_BYTES = 10_000_000


class EmailInput(BaseModel):
    recipient: str = Field(description="The recipient's email address.")
    subject: str = Field(description="Subject line of the email.")
    body: str = Field(description="Plain-text body of the email.")
    attachment_filename: str | None = Field(
        default=None,
        description="Optional generated report basename selected during human approval.",
    )


def _is_placeholder_sender(sender: str) -> bool:
    return (
        not sender
        or "ton_email" in sender
        or "@example.com" in sender
        or "@example.org" in sender
    )


def _create_ses_client():
    import boto3

    return boto3.client("ses", region_name=os.environ.get("AWS_REGION", "us-east-1"))


@tool("send_email", args_schema=EmailInput)
def send_email_tool(
    recipient: str,
    subject: str,
    body: str,
    attachment_filename: str | None = None,
) -> str:
    """Send an email via Amazon SES, optionally with a validated generated report."""
    sender = settings.EMAIL_SENDER
    logger.info("SEND_EMAIL: from=%s to=%s subject=%r", sender, recipient, subject)

    report = None
    if attachment_filename:
        try:
            report = resolve_generated_report(attachment_filename)
        except ValueError as exc:
            logger.warning("SEND_EMAIL: blocked attachment — %s", exc)
            return f"Email blocked: {exc}"

    if _is_placeholder_sender(sender):
        logger.warning("SEND_EMAIL: simulation mode — sender %r looks placeholder", sender)
        attachment_note = f" Pièce jointe : {report.name}." if report else ""
        return (
            f"SIMULATION SUCCÈS : Email virtuellement envoyé à {recipient} "
            f"avec le sujet '{subject}'.{attachment_note}"
        )

    try:
        client = _create_ses_client()
        if report is None:
            resp = client.send_email(
                Source=sender,
                Destination={"ToAddresses": [recipient]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
                },
            )
        else:
            message = EmailMessage()
            message["From"] = sender
            message["To"] = recipient
            message["Subject"] = subject
            message.set_content(body)
            content_type, _ = mimetypes.guess_type(report.name)
            maintype, subtype = (content_type or "application/octet-stream").split("/", 1)
            message.add_attachment(
                report.read_bytes(),
                maintype=maintype,
                subtype=subtype,
                filename=report.name,
            )
            raw = message.as_bytes()
            if len(raw) > MAX_RAW_EMAIL_BYTES:
                return "Email blocked: attachment makes the message exceed 10,000,000 bytes."
            resp = client.send_raw_email(
                Source=sender,
                Destinations=[recipient],
                RawMessage={"Data": raw},
            )
    except Exception as exc:
        from botocore.exceptions import BotoCoreError, ClientError

        if isinstance(exc, ClientError):
            code = exc.response.get("Error", {}).get("Code", "Unknown")
            msg = exc.response.get("Error", {}).get("Message", str(exc))
            logger.error("SEND_EMAIL: SES rejected — %s: %s", code, msg)
            return f"Erreur SES ({code}) : {msg}"
        if isinstance(exc, BotoCoreError):
            logger.exception("SEND_EMAIL: boto layer failed")
            return f"Erreur réseau SES : {exc}"
        raise

    message_id = resp.get("MessageId", "<unknown>")
    logger.info("SEND_EMAIL: sent successfully, MessageId=%s", message_id)
    return f"Email envoyé avec succès via SES (MessageId={message_id})."
