import smtplib
import os
from email.mime.text import MIMEText
from dotenv import load_dotenv

# Charge les variables du .env
load_dotenv()

sender = os.getenv("EMAIL_SENDER")
password = os.getenv("EMAIL_PASSWORD")
server_host = os.getenv("EMAIL_SMTP_SERVER")
port = int(os.getenv("EMAIL_SMTP_PORT", 465))

print(f"🔍 DIAGNOSTIC DE CONFIGURATION :")
print(f" - Email : '{sender}'")
print(f" - Mot de passe (longueur) : {len(password) if password else 0} caractères")
print(f" - Serveur : {server_host}:{port}")

if not sender or not password:
    print("❌ ERREUR : L'email ou le mot de passe est vide dans le fichier .env")
    exit()

# Test de connexion
print("\n📡 Tentative de connexion au serveur SMTP Google...")
try:
    with smtplib.SMTP_SSL(server_host, port) as server:
        print("   ✅ Connexion SSL réussie.")
        print("🔑 Tentative de login...")
        server.login(sender, password)
        print("   ✅ LOGIN RÉUSSI ! Vos identifiants sont corrects.")

        # Envoi d'un mail de test à soi-même
        msg = MIMEText("Ceci est un test de connexion réussi.")
        msg["Subject"] = "Test Debug Agent IA"
        msg["From"] = sender
        msg["To"] = sender

        server.sendmail(sender, sender, msg.as_string())
        print("   ✅ EMAIL ENVOYÉ ! Tout fonctionne.")

except smtplib.SMTPAuthenticationError:
    print("\n❌ ÉCHEC AUTHENTIFICATION (Erreur 535)")
    print("👉 Causes probables :")
    print(
        "   1. Ce n'est pas un 'Mot de passe d'application' (c'est votre mot de passe Gmail normal ?)"
    )
    print("   2. Il y a des espaces dans le mot de passe dans le fichier .env")
    print(
        "   3. L'adresse email ne correspond pas au compte qui a généré le mot de passe."
    )
except Exception as e:
    print(f"\n❌ ERREUR TECHNIQUE : {e}")
