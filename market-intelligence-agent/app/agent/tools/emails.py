import smtplib
from email.mime.text import MIMEText
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from app.core.config import settings


# 1. Le "Contrat" : Ce que le LLM doit fournir pour utiliser l'outil
class EmailInput(BaseModel):
    recipient: str = Field(description="L'adresse email du destinataire")
    subject: str = Field(description="Le sujet de l'email")
    body: str = Field(description="Le corps du mail (le contenu principal)")


# 2. La Fonction : Ce qui se passe quand l'outil est appelé
@tool("send_email", args_schema=EmailInput)
def send_email_tool(recipient: str, subject: str, body: str):
    """Utilise cet outil pour envoyer un email professionnel avec un rapport ou une réponse."""

    print(f"📧 [TOOL] ACTION REQUISE : Envoi d'email à {recipient}...")

    # Simulation si l'utilisateur n'a pas configuré ses vraies clés SMTP
    if "ton_email" in settings.EMAIL_SENDER or "ton_mdp" in settings.EMAIL_PASSWORD:
        return f"SIMULATION SUCCÈS : Email virtuellement envoyé à {recipient} avec le sujet '{subject}'."

    # Vrai envoi via Gmail/SMTP
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = settings.EMAIL_SENDER
    msg["To"] = recipient

    try:
        with smtplib.SMTP_SSL(
            settings.EMAIL_SMTP_SERVER, settings.EMAIL_SMTP_PORT
        ) as server:
            server.login(settings.EMAIL_SENDER, settings.EMAIL_PASSWORD)
            server.sendmail(settings.EMAIL_SENDER, recipient, msg.as_string())
        return "Email envoyé avec succès !"
    except Exception as e:
        return f"Erreur critique lors de l'envoi : {str(e)}"
