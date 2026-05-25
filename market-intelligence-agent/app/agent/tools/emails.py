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
import os

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailInput(BaseModel):
    recipient: str = Field(description="The recipient's email address.")
    subject: str = Field(description="Subject line of the email.")
    body: str = Field(description="Plain-text body of the email.")


def _is_placeholder_sender(sender: str) -> bool:
    return (
        not sender
        or "ton_email" in sender
        or "@example.com" in sender
        or "@example.org" in sender
    )


@tool("send_email", args_schema=EmailInput)
def send_email_tool(recipient: str, subject: str, body: str) -> str:
    """Send a plain-text email via Amazon SES. Use this for reports, replies,
    or notifications addressed to a single recipient."""
    sender = settings.EMAIL_SENDER
    logger.info("SEND_EMAIL: from=%s to=%s subject=%r", sender, recipient, subject)

    if _is_placeholder_sender(sender):
        logger.warning("SEND_EMAIL: simulation mode — sender %r looks placeholder", sender)
        return f"SIMULATION SUCCÈS : Email virtuellement envoyé à {recipient} avec le sujet '{subject}'."

    region = os.environ.get("AWS_REGION", "us-east-1")
    client = boto3.client("ses", region_name=region)
    try:
        resp = client.send_email(
            Source=sender,
            Destination={"ToAddresses": [recipient]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": body, "Charset": "UTF-8"}},
            },
        )
    except ClientError as e:
        # Most common SES errors at this layer:
        # - MessageRejected: identity unverified, or sandbox+unverified-recipient
        # - AccessDeniedException: IAM doesn't allow SendEmail on this identity
        # - Throttling: 1/sec sandbox rate exceeded
        code = e.response.get("Error", {}).get("Code", "Unknown")
        msg = e.response.get("Error", {}).get("Message", str(e))
        logger.error("SEND_EMAIL: SES rejected — %s: %s", code, msg)
        return f"Erreur SES ({code}) : {msg}"
    except BotoCoreError as e:
        logger.exception("SEND_EMAIL: boto layer failed")
        return f"Erreur réseau SES : {e}"

    message_id = resp.get("MessageId", "<unknown>")
    logger.info("SEND_EMAIL: sent successfully, MessageId=%s", message_id)
    return f"Email envoyé avec succès via SES (MessageId={message_id})."
