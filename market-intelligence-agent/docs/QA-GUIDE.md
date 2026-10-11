# Guide QA - Research (voix + texte) et agents spécialisés

Ce guide permet de rejouer vous-même les 15 contrôles de la passe QA du 2026-10-11. Chaque section est indépendante.

## Démarrage

Depuis le dossier `market-intelligence-agent/` de ce worktree, avec le `.env` rempli :

```bash
# Terminal 1 - backend (SANS --reload)
uv run uvicorn app.api.server:app --host 0.0.0.0 --port 8000

# Terminal 2 - frontend
cd frontend && npm run dev
```

Ouvrez ensuite http://localhost:5173/research (Chrome recommandé).

- Si les ports 8000 / 5173 sont déjà pris par un autre checkout, arrêtez cet autre processus avant de relancer.
- Pour la voix : autorisez le micro quand Chrome le demande (icône cadenas dans la barre d'adresse > Micro > Autoriser). Il faut une `OPENAI_API_KEY` valide dans `.env`.
- Avant chaque test : cliquez sur **+ New session** dans la navigation de gauche pour obtenir un fil vierge (ne réutilisez jamais un fil `clients_<id>`).
- La mémoire des faits (`save_memory`) est en RAM : un redémarrage du backend l'efface.

### Où regarder

- **Rail Intelligence / activité** (colonne de droite, titre "Agent activity" ; sur petit écran, bouton "Open activity") : liste le spécialiste routé (`portfolio_agent`, `rag_agent`...) et les outils appelés (`concentration_screen`...).
- **Carte d'approbation** : apparaît dans le chat quand une action à effet de bord est proposée (`send_email`, `write_file`, `save_memory`), avec les boutons Approve / Reject.
- **Bulle de sous-titre en direct** : bulle en pointillé, alignée à droite au-dessus du champ de saisie, qui affiche ce que vous dites pendant que vous parlez ; elle disparaît à la fin du tour et est remplacée par un vrai message.
- **Messages du chat** : après la réponse vocale, un message utilisateur et un message assistant doivent apparaître et rester après rechargement de la page.
- **Journal du backend** : la sortie du Terminal 1.

### ATTENTION : emails réels

Si vous cliquez **Approve** (ou dites "approve") sur une carte `send_email`, un **vrai email est envoyé via Amazon SES**. Seules les adresses présentes dans la table `clients` (colonne `email`) sont acceptées, mais l'envoi est réel. **Pour tester sans risque, choisissez toujours Reject.**

Noms de clients utilisables pour les tests (extraits de `customers.db`) : Margaret Collins, Robert Hayes, Thomas Reed, Linda Park.

---

## 1. Transcription vocale

**Objectif** : prouver que la voix s'affiche en direct puis devient des messages persistants (user + assistant) et que la réponse est fondée sur l'outil `concentration_screen` (portfolio_agent).

**Prérequis** : backend + frontend lancés, micro autorisé, `/research`, **+ New session**.

**Étapes**
1. Cliquez sur le bouton micro "Start voice mode" dans la zone de saisie.
2. Dites : "Which clients have more than 30 percent of their portfolio in one stock?"
3. Observez la bulle en pointillé pendant que vous parlez, puis la réponse audio.
4. Rechargez la page (F5) et revenez sur `/research` avec le même fil.

**Résultat attendu**
- La bulle grandit pendant la parole, puis disparaît.
- Un message utilisateur et un message assistant apparaissent ; l'audio est joué.
- Après rechargement, les deux messages sont toujours là.
- Rail : `portfolio_agent` + `concentration_screen`.
- Les noms cités correspondent au résultat de `concentration_screen` (ex. Robert Hayes GOOGL ~68 %, Thomas Reed NVDA ~66 %, James Whitaker NVDA ~59 %...). Vérifiez avec le même test en texte (section 3) ou avec `customers.db`.

**Si ça échoue** : permission micro refusée (cadenas Chrome) ; `OPENAI_API_KEY` manquante ; journal backend (`POST /gptlive/session` en erreur) ; backend lancé depuis un autre checkout ; origine du frontend non autorisée (variable `VOICE_ALLOWED_ORIGINS` si vous n'utilisez pas le port 5173).

## 2. HITL vocal (rejet d'un email)

**Objectif** : prouver que l'approbation humaine fonctionne en voix (email_agent + `send_email`) et que rejeter n'envoie rien.

**Prérequis** : comme la section 1, session neuve. **Choisissez Reject.**

**Étapes**
1. Mode voix actif. Dites : "Send an email to Margaret Collins with a summary of her portfolio" (si l'agent demande l'adresse, dites : margaret.collins@example.com).
2. Une carte d'approbation apparaît. Cliquez **Reject** (ou dites "reject").

**Résultat attendu**
- La carte d'approbation `send_email` apparaît (rail : `email_agent`).
- Après Reject, le chat affiche l'annulation (action annulée / demande rejetée).
- Le journal backend ne montre aucun envoi SES.

**Si ça échoue** : l'agent répond sans carte (reformulez avec l'adresse exacte de `customers.db`) ; micro/WebRTC (voir section 1) ; vérifiez `EMAIL_SENDER` dans `.env`.

## 3. Concentration tapée

**Objectif** : même question en texte, routage vers portfolio_agent.

**Prérequis** : session neuve sur `/research`.

**Étapes** : tapez "Which clients have more than 30 percent of their portfolio in one stock?" puis Entrée.

**Résultat attendu**
- Rail : `portfolio_agent` et `concentration_screen`.
- Liste d'environ 18 clients distincts, tous présents dans `customers.db` (Robert Hayes, Thomas Reed, James Whitaker, Margaret Collins...). Comparez avec :
  ```bash
  curl -s localhost:8000/data/briefing/client-alerts
  ```

**Si ça échoue** : erreur affichée = regardez le journal backend ; `customers.db` absent ou vide (`uv run python create_db.py`) ; yfinance lent (attendez ~15 s).

## 4. RAG

**Objectif** : prouver rag_agent + `search_knowledge_base` (Pinecone).

**Prérequis** : session neuve ; clés `PINECONE_API_KEY` et `PINECONE_INDEX_NAME` valides ; documents ingérés (`uv run python -m app.ingest`).

**Étapes** : tapez "What does Amazon's 2024 annual report say about AI?"

**Résultat attendu**
- Rail : `rag_agent` + `search_knowledge_base`.
- La réponse contient `[Source: Amazon-2024-Annual-Report.pdf, page N]`.

**Si ça échoue** : index Pinecone vide ou clé invalide (journal backend) ; `app/agent/tools/kb_documents.json` absent.

## 5. Données de marché

**Objectif** : prouver finance_agent + `yfinance_get_ticker_info`.

**Prérequis** : session neuve ; accès Internet.

**Étapes** : tapez "What is Apple's current stock price?"

**Résultat attendu**
- Rail : `finance_agent` + `yfinance_get_ticker_info`.
- Une carte de cotation AAPL (prix courant). Le texte seul peut se limiter à "Here's AAPL's current quote." : le prix est dans la carte. Comparez avec Yahoo Finance ou `curl -s localhost:8000/data/briefing/watchlist` (champ AAPL `price`).

**Si ça échoue** : yfinance bloqué ou limité (journal), `YFINANCE_TIMEOUT_S` trop bas.

## 6. HITL texte (écriture de fichier)

**Objectif** : prouver filesystem_agent + `write_file` derrière une approbation.

**Prérequis** : session neuve.

**Étapes**
1. Tapez "Write a file qa-note.txt with the text hello".
2. Une carte d'approbation `write_file` apparaît : cliquez **Approve**.
3. Vérifiez le disque :
   ```bash
   cat data/workspace/qa-note.txt   # doit afficher : hello
   rm data/workspace/qa-note.txt    # nettoyage
   ```

**Résultat attendu** : rail `filesystem_agent` + `write_file` ; confirmation dans le chat ; fichier présent avec `hello`.

**Si ça échoue** : Node/npx absent (serveur MCP filesystem) ; journal backend ; dossier `data/workspace/` inexistant.

## 7. Continuité voix vers texte

**Objectif** : prouver que la voix et le texte partagent le même fil.

**Prérequis** : faire d'abord la section 1 (même session, ne cliquez pas sur New session).

**Étapes** : dans le champ texte (après avoir arrêté la voix si nécessaire), tapez "summarize that in one sentence".

**Résultat attendu** : une phrase qui reprend le résultat de concentration (clients/actions cités plus haut). Le rail peut afficher un autre spécialiste, ce n'est pas bloquant tant que la réponse s'appuie sur l'historique.

**Si ça échoue** : l'agent dit ne pas savoir de quoi on parle = la voix n'a pas été enregistrée dans le fil (voir section 1, rechargement) ; vous avez cliqué New session entre les deux.

## 8. Briefing

**Objectif** : vérifier la page `/briefing` (indices, movers, actualités, alertes clients).

**Prérequis** : backend lancé, accès Internet.

**Étapes** : ouvrez http://localhost:5173/briefing ; ouvrez la console du navigateur (F12).

**Résultat attendu** : indices, plus gros mouvements, actualités, alertes de concentration clients ; aucune erreur rouge dans la console. Vérification API (200 attendu ; une première ouverture à froid peut prendre 10 à 60 s) :
```bash
curl -s -o /dev/null -w "%{http_code}\n" localhost:5173/data/briefing/indices
curl -s -o /dev/null -w "%{http_code}\n" localhost:5173/data/briefing/client-alerts
```

**Si ça échoue** : yfinance lent (patientez) ; clé OpenAI / Tavily pour les actualités et le narratif ; journal backend.

## 9. Clients et Reports

**Objectif** : liste des clients, ouverture d'un espace client, génération d'un rapport.

**Étapes**
1. Ouvrez `/clients` : la liste (25 clients) s'affiche ; cliquez un client pour ouvrir son espace.
2. Ouvrez `/reports` et générez un rapport pour un client.

**Résultat attendu** : espace client chargé ; fichier `.xlsx` créé dans `data/workspace/reports/` et proposé au téléchargement.

**Si ça échoue** : `customers.db` manquant (`uv run python create_db.py`) ; journal backend pour l'erreur de génération.

## 10. Data

**Objectif** : la page `/data` liste documents et clients (sans import).

**Étapes** : ouvrez `/data`. N'importez rien.

**Résultat attendu** : 5 documents (2026-Annual-Report-Web, Amazon-2024, Goldman-Sachs-GS-2025, NVIDIA-NVDA-2026, Tesla-TSLA-Q2-2026) et la liste des clients.

**Si ça échoue** : `curl -s localhost:5173/data/documents` ; backend arrêté ; manifeste `kb_documents.json`.

## 11. Surfaces supprimées

**Objectif** : confirmer que l'ancienne UI (Classic, Streamlit, endpoint de transcription) a disparu.

**Étapes**
1. Ouvrez http://localhost:5173/classic : aucune ancienne interface de chat (pas de champ "Ask the agent...", pas de bouton voix).
2. Dans un terminal :
   ```bash
   curl -s -o /dev/null -w "%{http_code}" localhost:8000/voice/x/transcript
   ```
   Doit afficher `404`.
3. Vérifiez qu'aucun processus n'écoute sur le port 8080 :
   ```bash
   netstat -ano | grep ":8080 .*LISTEN"
   ```
   (aucune sortie attendue)

**Résultat attendu** : 404 ; rien sur 8080 ; pas de chat Classic.

**Si ça échoue** : un vieux Streamlit tourne encore (arrêtez le processus qui écoute sur 8080) ; backend d'un autre checkout (ancienne branche) sur le port 8000.

## 12. API backend

**Objectif** : prouver l'API : santé, flux SSE, interruption HITL, rejet.

**Prérequis** : backend sur le port 8000.

**Étapes**
```bash
curl localhost:8000/health
curl -sN -X POST localhost:8000/stream -H 'Content-Type: application/json' \
  -d '{"query": "Send an email to margaret.collins@example.com with a short summary of Margaret Collins portfolio", "thread_id": "qa-guide-12"}'
curl -s -X POST localhost:8000/approve -H 'Content-Type: application/json' \
  -d '{"thread_id": "qa-guide-12", "approved": false}'
```
Utilisez un nouveau `thread_id` à chaque essai. **N'envoyez jamais `"approved": true`** : cela enverrait un vrai email.

**Résultat attendu**
- `/health` : `{"status":"ok",...}`.
- Le flux SSE contient des évènements `node` (spécialiste `email_agent`) puis `event: interrupted`.
- `/approve` : `"status":"completed"` avec un message indiquant que l'envoi a été rejeté.

**Si ça échoue** : si l'agent demande l'adresse au lieu d'interrompre, redonnez une adresse présente dans `clients.email` ; backend non démarré ; thread id déjà utilisé.

## 13. Spécialiste navigateur

**Objectif** : prouver browser_agent + `browser_navigate`.

**Prérequis** : session neuve ; Chromium Playwright installé (`npx -y @playwright/mcp@latest install-browser chrome-for-testing`).

**Étapes** : tapez "Open https://www.example.com and tell me the page title".

**Résultat attendu** : rail `browser_agent` + `browser_navigate` (et éventuellement `browser_snapshot`) ; la réponse contient "Example Domain".

**Si ça échoue** : Chromium non installé ; `npx` absent ; journal backend (erreur MCP playwright).

## 14. Spécialiste mémoire

**Objectif** : prouver memory_agent : `save_memory` avec approbation, puis rappel.

**Prérequis** : session neuve ; backend non redémarré entre la sauvegarde et le rappel (mémoire en RAM).

**Étapes**
1. Tapez "Remember that my preferred report format is Excel" ; sur la carte `save_memory`, cliquez **Approve**.
2. Tapez ensuite "What is my preferred report format?" (même session ou nouvelle session).
3. Si l'agent répond qu'il ne sait pas, tapez "What do you remember about me? List my saved memories."

**Résultat attendu** : rail `memory_agent` + `save_memory`, puis `recall_memory` ou `list_memories` ; réponse "Excel".

**Remarque (constat de la passe QA du 2026-10-11)** : avec la formulation exacte de l'étape 2, le modèle a parfois répondu sans appeler d'outil (il dit ne rien savoir, ou répond depuis le contexte via `rag_agent`). L'étape 3 fonctionne (`list_memories`). C'est un point ouvert côté prompt du spécialiste mémoire.

**Si ça échoue** : backend redémarré (mémoire perdue) ; carte d'approbation non validée.

## 15. Résumé du routage

**Objectif** : confirmer que les 7 spécialistes sont atteints.

**Étapes** : relevez, dans le rail, le spécialiste de chaque test.

**Résultat attendu**

| Spécialiste | Section |
|---|---|
| portfolio_agent | 3 |
| rag_agent | 4 |
| finance_agent | 5 |
| filesystem_agent | 6 |
| browser_agent | 13 |
| memory_agent | 14 |
| email_agent | 2 / 12 |

**Si ça échoue** : un spécialiste manquant = refaites la section correspondante avec une session neuve ; regardez le journal backend pour une erreur de routage du superviseur.
