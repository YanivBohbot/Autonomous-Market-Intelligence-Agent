import logging
import smtplib
from email.mime.text import MIMEText
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailInput(BaseModel):
    recipient: str = Field(description="L'adresse email du destinataire")
    subject: str = Field(description="Le sujet de l'email")
    body: str = Field(description="Le corps du mail (le contenu principal)")


@tool("send_email", args_schema=EmailInput)
def send_email_tool(recipient: str, subject: str, body: str) -> str:
    """Utilise cet outil pour envoyer un email professionnel avec un rapport ou une réponse."""
    logger.info("SEND_EMAIL: Sending to %s", recipient)
    # Simulation gate: any obviously-placeholder sender or password keeps the
    # tool from actually trying to SMTP. Covers the original 'ton_email' /
    # 'ton_mdp' French defaults plus '@example.com' senders left in IaC.
    if (
        "ton_email" in settings.EMAIL_SENDER
        or "ton_mdp" in settings.EMAIL_PASSWORD
        or "@example.com" in settings.EMAIL_SENDER
    ):
        logger.warning("SEND_EMAIL: Simulation mode — no real email sent (sender=%s)", settings.EMAIL_SENDER)
        return f"SIMULATION SUCCÈS : Email virtuellement envoyé à {recipient} avec le sujet '{subject}'."

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_SENDER
    msg["To"] = recipient
    port = int(settings.EMAIL_SMTP_PORT)
    try:
        # Port 465 → SSL from connect. Port 587 (and others) → plain SMTP
        # connection upgraded with STARTTLS. Using SMTP_SSL on 587 hangs the
        # handshake; using STARTTLS on 465 fails because the server expects
        # TLS-on-connect. Pair the function to the port.
        if port == 465:
            with smtplib.SMTP_SSL(settings.EMAIL_SMTP_SERVER, port, timeout=20) as server:
                server.login(settings.EMAIL_SENDER, settings.EMAIL_PASSWORD)
                server.sendmail(settings.EMAIL_SENDER, recipient, msg.as_string())
        else:
            with smtplib.SMTP(settings.EMAIL_SMTP_SERVER, port, timeout=20) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(settings.EMAIL_SENDER, settings.EMAIL_PASSWORD)
                server.sendmail(settings.EMAIL_SENDER, recipient, msg.as_string())
        logger.info("SEND_EMAIL: Sent successfully to %s", recipient)
        return "Email envoyé avec succès !"
    except Exception as e:
        logger.error("SEND_EMAIL: Failed — %s", e)
        return f"Erreur critique lors de l'envoi : {str(e)}"
