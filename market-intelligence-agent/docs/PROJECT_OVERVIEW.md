# Market Intelligence Agent : le projet de bout en bout

Ce document explique ce qu'on a construit :
- le produit ;
- l'architecture ;
- l'infrastructure ;
- les choix techniques ;
- les concepts LangChain / LangGraph qui rendent le tout possible.

---

## 1. Le produit

Market Intelligence Agent est un assistant IA de **gestion de patrimoine** (wealth management) pour un conseiller financier. Il sait :

- analyser les marchés : cours, historiques, actualités, comparaison d'entreprises ;
- gérer les portefeuilles clients : valeur, plus-values, concentration, scénarios « et si… », alertes de watchlist ;
- chercher dans les rapports annuels d'entreprises (PDF) et sur le web ;
- naviguer sur un vrai site web et en faire des captures d'écran ;
- écrire des rapports dans un espace de fichiers ;
- envoyer des emails aux clients ;
- retenir des faits sur l'utilisateur, d'une session à l'autre.

**Règle d'or :** avant toute action qui a un effet réel (envoyer un email, écrire un fichier, mémoriser un fait), l'agent **s'arrête et demande l'accord d'un humain**.

Le produit a trois interfaces, branchées sur le même agent :

| Interface | Description |
|---|---|
| **Console React** | pages Research, Briefing, Clients, Reports, Data |
| **Mode vocal** | conversation parlée en temps réel dans la page Research |
| **Production AWS** | l'agent tourne sur Amazon Bedrock AgentCore |

---

## 2. Vue d'ensemble de l'architecture

```
                ┌─────────────────────── Console React (Vite) ───────────────────────┐
                │  Research (chat + historique + voix)   Clients   Reports   Data     │
                └──────────────┬──────────────────────┬─────────────────┬────────────┘
                     AG-UI (SSE)│            SSE /stream│      WebRTC     │ REST
                               ▼                      ▼   (voix)        ▼
                ┌──────────────────────────── FastAPI ───────────────────────────────┐
                │ /copilot/market-desk  /stream  /approve  /gptlive/session  /data   │
                │ /conversations  /health                                            │
                └──────────────────────────────┬─────────────────────────────────────┘
                                               ▼
                ┌──────────────── Graphe LangGraph multi-agents (unique) ─────────────┐
                │ load_client_context → record_question → supervisor ⇄ spécialistes   │
                │                                         → finalize_turn → END       │
                │  Spécialistes : rag · finance · portfolio · browser · email ·       │
                │                 filesystem · memory  (create_agent + middlewares)   │
                └───────┬───────────────────┬────────────────────┬────────────────────┘
                        ▼                   ▼                    ▼
                 Checkpointer          Store LangGraph        Outils
                 (conversations)       (mémoire longue,       MCP (SQLite, Yahoo,
                 SQLite / AgentCore    historique, vecteurs)  fichiers, Playwright)
                                                              + outils Python
                                                              + Pinecone, Tavily, SES
```

**Idée centrale :** il existe **un seul graphe**. Il est compilé une fois au démarrage de FastAPI et partagé par toutes les entrées : le chat texte, l'interface AG-UI, la voix et AgentCore. Une conversation est identifiée par son `thread_id`. Elle peut commencer à l'écrit, continuer à la voix et reprendre après un redémarrage du serveur.

---

## 3. Le cœur : un système multi-agents (LangGraph)

### 3.1 Le pattern Superviseur / Routeur

```
load_client_context → record_question → supervisor → <spécialiste> → supervisor → finalize_turn → END
```

**`load_client_context`** charge le contexte du client actif quand la conversation porte sur un client précis.

**`record_question`** enregistre la question et l'indexe dans l'historique des conversations.

**`supervisor`** décide qui doit travailler. Il combine deux mécanismes.
- Des **règles déterministes en Python** :
  - une limite du nombre de sauts ;
  - une fin forcée après une réponse ;
  - l'enchaînement portefeuille → email ;
  - un « save it » qui reste sur le bon agent ;
  - un repli sur le RAG si personne n'a répondu.
- **Une seule décision LLM**, prise par un `router_agent`. C'est un `create_agent` sans outils, avec une sortie structurée `RoutingDecision`.

**Les spécialistes** font le travail, puis rendent la main au superviseur.

**`finalize_turn`** clôt le tour proprement et ajoute un extrait de la réponse à l'index de l'historique.

### 3.2 Les 7 spécialistes

Chaque spécialiste est un `create_agent` de LangChain, ajouté au graphe comme **sous-graphe**, avec son prompt, ses outils et ses middlewares.

| Spécialiste | Rôle | Outils principaux |
|---|---|---|
| `rag_agent` | rapports d'entreprises et web | `search_knowledge_base`, `web_search` |
| `finance_agent` | marchés | outils Yahoo Finance, `compare_companies`, `pct_change` |
| `portfolio_agent` | portefeuilles clients | `read_query`, `portfolio_metrics`, `concentration_screen`, `simulate_portfolio_change`, `watchlist_alerts` |
| `browser_agent` | navigation web réelle | `browser_navigate`, `browser_snapshot`, `browser_take_screenshot` |
| `email_agent` | emails clients | `send_email` (HITL) |
| `filesystem_agent` | fichiers et rapports | `read_text_file`, `list_directory`, `write_file` (HITL) |
| `memory_agent` | mémoire de l'utilisateur | `recall_memory`, `list_memories`, `save_memory` (HITL) |

**Pourquoi un sous-graphe par spécialiste ?**
- Chaque agent a un périmètre d'outils réduit : moins d'erreurs de choix, et des prompts plus courts.
- La sécurité est réglée par agent. Par exemple, seuls les agents qui envoient des données à des tiers masquent les emails.
- Les tests sont isolés.
- On peut ajouter un agent sans toucher aux autres.

---

## 4. Les outils et MCP

### 4.1 MCP (Model Context Protocol)

MCP est un protocole standard qui permet de brancher des outils externes à un agent. Un seul `MultiServerMCPClient` (de `langchain-mcp-adapters`) charge tous les serveurs :

| Serveur MCP | Ce qu'il apporte |
|---|---|
| `mcp-server-sqlite` | la base clients `customers.db` : entreprises, clients, transactions, positions, watchlists |
| `yfmcp` | Yahoo Finance : infos d'une action, historique de prix |
| `@modelcontextprotocol/server-filesystem` | fichiers, limités au dossier `data/workspace/` |
| `@playwright/mcp` | un navigateur Chromium headless. Une seule session longue est partagée, pour que la navigation et la capture d'écran agissent sur la même page. |

En production, ces serveurs deviennent des **fonctions Lambda** derrière **AgentCore Gateway** (voir la section 11).

### 4.2 Nos propres outils déterministes

Un principe important du projet : **les calculs se font en Python, pas dans le LLM**. Le modèle choisit l'outil et les filtres ; l'outil charge lui-même les données et calcule. Le LLM ne recopie jamais de chiffres, donc même un petit modèle (gpt-4o-mini) donne des réponses exactes.

| Outil | Ce qu'il fait |
|---|---|
| `concentration_screen` | les clients qui ont plus de 30 % de leur portefeuille dans une seule action (les ETF sont exclus) |
| `compare_companies` | 2 à 4 actions côte à côte : prix, capitalisation, P/E, performance |
| `simulate_portfolio_change` | scénario « et si » sur un portefeuille, sans jamais écrire dans la base |
| `watchlist_alerts` | les alertes de watchlist comparées aux prix en direct |
| `portfolio_metrics` / `pct_change` | les mathématiques de portefeuille |
| `ask_user_choice` | affiche une carte de choix à l'utilisateur et attend sa réponse |

Le fichier `docs/TOOLS.md` est le registre officiel de tous les outils. Une règle du projet impose de le garder à jour.

---

## 5. Le RAG hybride (recherche dans les rapports)

### 5.1 Ingestion (`app/ingest.py`, `app/rag/`)

1. **Chargement** : `PyPDFLoader` lit les PDF.
2. **Découpage** : `RecursiveCharacterTextSplitter`, en morceaux de 1000 caractères avec 200 de recouvrement.
3. **Embeddings** : `OpenAIEmbeddings` avec `text-embedding-3-small`.
4. **Stockage** : `PineconeVectorStore`.
   - Les identifiants sont **déterministes** (sha256), donc réindexer un PDF écrase au lieu de dupliquer.
   - Les mêmes morceaux alimentent aussi un corpus **BM25** pour la recherche par mots-clés.

### 5.2 Recherche (`RerankingRetriever`)

1. Une **recherche vectorielle** (par le sens) donne jusqu'à 20 candidats, au-dessus d'un seuil de pertinence.
2. Une **recherche BM25** (par mots-clés) ajoute des candidats, pour les noms propres et les chiffres.
3. Les doublons sont supprimés.
4. Un **reranker** (`PineconeRerank`, `bge-reranker-v2-m3`) reclasse le tout.
5. Chaque résultat est cité : `[Source: fichier, page N]`.

**Décidé par la mesure :** sur un benchmark de 27 questions, la recherche hybride est passée de 22 à 25 bonnes réponses. Trois autres idées ont été testées puis **rejetées faute de gain mesuré** : un autre découpage, un autre loader et l'analyse des tableaux.

---

## 6. Sécurité et garde-fous (défense en profondeur)

| Couche | Mécanisme |
|---|---|
| **Validation humaine (HITL)** | `send_email`, `write_file` et `save_memory` s'arrêtent. L'humain approuve, rejette ou modifie l'action. |
| **Cartes bancaires, blocage** | Une carte dans la question arrête le tour **avant tout appel au modèle** (`block_credit_cards`, un `@before_agent`). |
| **Cartes bancaires, masquage** | `PIIMiddleware` masque les numéros dans les entrées, les sorties et les résultats d'outils. |
| **Emails** | Masqués pour les agents qui parlent à des tiers (web, navigateur, rapports), conservés pour ceux qui en ont besoin. |
| **Modération** | `OpenAIModerationMiddleware` contrôle le contenu en entrée et en sortie. |
| **Destinataires** | `EmailRecipientGuard` n'autorise l'envoi qu'aux vraies adresses clients de la base, vérifiées après l'approbation. |
| **Fichiers** | Le serveur MCP ne peut pas sortir de `data/workspace/`. |
| **Secrets** | Les clés restent côté serveur, y compris pour la voix. En production, ce sont des secrets AWS chiffrés. |

---

## 7. Fiabilité, contexte et coûts

### 7.1 Fiabilité

| Mécanisme | Ce qu'il fait |
|---|---|
| `ModelRetryMiddleware` | réessaie quand OpenAI a une erreur passagère (backoff exponentiel) |
| `ModelFallbackMiddleware` | bascule sur Claude si OpenAI reste en échec (optionnel) |
| `ToolErrorMiddleware` | une erreur d'outil devient un message, et la conversation n'est pas « empoisonnée » |
| `ToolRetryMiddleware` | réessaie **seulement les outils en lecture seule** : un email ne part jamais deux fois |

### 7.2 La fenêtre de contexte

| Mécanisme | Ce qu'il fait |
|---|---|
| `ContextEditingMiddleware` | Au-delà de 4000 tokens, les résultats d'outils plus vieux que le tour actuel et les 2 précédents deviennent `[cleared]`, **seulement dans ce qui est envoyé au modèle**. L'historique et les cartes à l'écran ne changent pas. Avant ce mécanisme, une conversation de 6 questions envoyait environ 23 000 tokens à chaque appel. |
| `SummarizationMiddleware` | au-delà de 50 messages, les plus anciens sont résumés |
| `ModelCallLimitMiddleware` | 10 appels au modèle au maximum par tour |
| `ToolCallLimitMiddleware` | 3 recherches web et 5 navigations au maximum par tour |

---

## 8. La mémoire : checkpointer et store

LangGraph sépare deux types de mémoire :

| | **Checkpointer** (mémoire courte) | **Store** (mémoire longue) |
|---|---|---|
| Contenu | l'état complet de chaque conversation : messages, résultats d'outils, interruptions en attente | des données transversales : faits sur l'utilisateur, index des conversations |
| Clé | `thread_id` | namespace + clé |
| En local | `AsyncSqliteSaver`, dans `data/checkpoints.db` | `AsyncSqliteStore`, dans `data/store.db` |
| En production | `AgentCoreMemorySaver` | — |
| Utilité | reprendre une conversation, faire survivre une validation HITL à un redémarrage | mémoire utilisateur durable, historique consultable |

### L'historique des conversations (page Research)

- Chaque conversation Research a une fiche dans le namespace `("conversations",)` du store. La fiche contient :
  - le titre ;
  - les dates ;
  - les dernières questions et des extraits des dernières réponses.
- Le store a un **index vectoriel** sur ces fiches. On peut donc **chercher par le sens** : « semi-conducteurs » retrouve « Compare NVDA vs AMD ».
- Le panneau permet de lister, chercher, renommer et supprimer les conversations. Il se plie.
- Supprimer une conversation efface ses checkpoints et sa fiche.

---

## 9. L'interface : React, CopilotKit et AG-UI

- **Stack :** React, TypeScript, Vite, Tailwind et react-router, avec les pages Research, Briefing, Clients, Reports et Data.
- **AG-UI** est un protocole qui fait circuler en streaming l'état d'un agent vers une interface. Il est branché sur LangGraph par `ag-ui-langgraph` et côté React par **CopilotKit**.
- **Generative UI :** l'agent ne renvoie pas seulement du texte, il fait apparaître des **cartes interactives** :
  - une carte de comparaison d'entreprises (avec graphique) ;
  - une carte « what-if » de portefeuille ;
  - une carte d'alertes ;
  - un tableau de résultat SQL ;
  - une carte de choix (boutons ou cases à cocher), qui interrompt le graphe jusqu'à la réponse ;
  - les cartes de validation HITL ;
  - des suggestions de questions de suivi.
- **SSE (`/stream`)** montre en direct quel spécialiste travaille et quel outil tourne.
- **Les pages Briefing, Clients, Reports et Data** :
  - le briefing de marché ;
  - les fiches clients ;
  - les rapports Excel ;
  - l'import de PDF et de fichiers de données (aperçu, puis confirmation).

  Elles sont volontairement **non agentiques** : des routes REST déterministes, sans LLM.

---

## 10. Le mode vocal

Le mode vocal utilise **OpenAI GPT-Live** en mode délégation :

1. Le navigateur ouvre une connexion **WebRTC** directement avec OpenAI. La négociation passe par notre serveur, donc la clé API ne quitte jamais le serveur.
2. Le serveur se branche sur la même session par un **WebSocket « sideband »** et reçoit les demandes de délégation.
3. Il fait exécuter chaque demande par **le même graphe multi-agents**, sur la même conversation que le chat texte.
4. Les validations HITL se font à la voix (« oui » / « non », en anglais ou en hébreu) ou par les mêmes cartes visuelles.
5. La transcription s'affiche dans le chat. Une seule réponse, écrite ou vocale, peut tourner à la fois sur une conversation (un « verrou de tour »).

---

## 11. L'infrastructure de production (AWS)

| Brique AWS | Rôle |
|---|---|
| **Amazon Bedrock AgentCore Runtime** | fait tourner l'agent dans un conteneur, via les points d'entrée `/invocations` et `/ping` |
| **AgentCore Gateway** | expose les outils MCP de production |
| **AWS Lambda** (3 fonctions) | les serveurs MCP en production : CRM, Yahoo Finance, fichiers |
| **AgentCore Browser** | le navigateur géré pour l'agent navigateur |
| **AgentCore Memory** | le checkpointer durable : une validation HITL fonctionne même si la reprise arrive sur un autre conteneur |
| **Amazon SES** | l'envoi réel des emails |
| **Amazon Cognito** | l'authentification |
| **Secrets Manager** | les clés (OpenAI, Pinecone, Tavily…) |
| **CloudWatch** | l'observabilité |

### Infrastructure en code et déploiement continu

- **AWS CDK (Python)** : un stack par responsabilité (runtime, gateway, Lambdas MCP, navigateur, stockage, secrets, observabilité).
- **GitHub Actions avec OIDC** : chaque push sur master déploie automatiquement. GitHub obtient des droits AWS temporaires, sans aucune clé stockée.
- **Versions épinglées** : `requirements.agentcore.txt` reprend exactement les versions de `uv.lock`, pour que la production exécute ce qui a été testé. Les versions du CLI CDK et de `aws-cdk-lib` sont épinglées ensemble.

---

## 12. Les concepts LangChain / LangGraph mis en œuvre

### 12.1 LangGraph : l'orchestration

| Concept | Utilisation dans le projet |
|---|---|
| **`StateGraph`** | le graphe principal : des nœuds (fonctions) et des arêtes (transitions), avec `START` et `END` |
| **State + reducers** | `SupervisorState` (TypedDict). Le reducer `add_messages` ajoute les messages au lieu de les écraser. |
| **Sous-graphes** | chaque spécialiste est un agent compilé, ajouté comme nœud du graphe principal |
| **Routage conditionnel** | le superviseur choisit le nœud suivant selon sa décision |
| **Checkpointer** | `AsyncSqliteSaver` en local, `AgentCoreMemorySaver` en production. Il sauvegarde l'état après chaque étape, par `thread_id`. |
| **Store** | `AsyncSqliteStore` avec index vectoriel. Lu dans les nœuds avec `get_store()`, et injecté dans les outils avec `InjectedStore`. |
| **`interrupt()` / `Command(resume=...)`** | met le graphe en pause pour attendre un humain, puis le relance avec sa décision (HITL, carte de choix) |
| **Streaming** | les événements par nœud, sous-graphe et token alimentent SSE et AG-UI |
| **`RunnableLambda` (sync + async)** | des nœuds avec une version asynchrone, pour écrire dans le store sans bloquer |

### 12.2 LangChain : les agents

| Concept | Utilisation dans le projet |
|---|---|
| **`create_agent`** | la fabrique officielle d'agents (modèle, outils, prompt, middlewares), utilisée pour les 7 spécialistes et le routeur |
| **Structured output** | `response_format=RoutingDecision` avec `ToolStrategy` : le routeur renvoie un objet validé, pas du texte libre |
| **Tools** | `@tool`, `StructuredTool`, `BaseTool`, avec un schéma d'arguments typé |
| **Outils MCP** | `MultiServerMCPClient` et `load_mcp_tools` transforment les outils MCP en outils LangChain |
| **Messages** | `HumanMessage`, `AIMessage`, `ToolMessage`, `SystemMessage` |
| **Chat models** | `ChatOpenAI` en principal ; Claude en secours, déclaré par l'identifiant `"anthropic:claude-sonnet-5-5"` dans `ModelFallbackMiddleware` |

### 12.3 LangChain : les middlewares

Le middleware est **le concept clé de LangChain 1.x** : on ajoute un comportement à un agent (sécurité, fiabilité, contexte) **sans modifier l'agent**. Chaque middleware s'accroche à un moment précis de la boucle :

| Hook | Moment | Exemple dans le projet |
|---|---|---|
| `before_agent` | avant que l'agent démarre | bloquer une carte bancaire |
| `before_model` / `after_model` | autour de chaque appel au modèle | modération, contrôle des destinataires d'email |
| `wrap_model_call` | enveloppe l'appel au modèle | retry, fallback, masquage des emails, édition du contexte |
| `wrap_tool_call` | enveloppe l'appel à un outil | retry des outils, conversion des erreurs, affichage |
| `@dynamic_prompt` | construit le prompt à chaque appel | la date du jour, le contexte du client, les documents disponibles |

Les middlewares officiels utilisés sont :
- `HumanInTheLoopMiddleware` ;
- `PIIMiddleware` ;
- `OpenAIModerationMiddleware` ;
- `ContextEditingMiddleware` ;
- `SummarizationMiddleware` ;
- `ModelRetryMiddleware` ;
- `ModelFallbackMiddleware` ;
- `ToolErrorMiddleware` ;
- `ToolRetryMiddleware` ;
- `ModelCallLimitMiddleware` ;
- `ToolCallLimitMiddleware`.

Les middlewares maison héritent d'`AgentMiddleware` :
- `RedactEmailsForModel` ;
- `EmailRecipientGuard` ;
- `ClearOldTurnToolResults`, une règle d'édition branchée dans le middleware officiel.

**L'ordre compte :** un middleware listé plus tôt enveloppe ceux qui suivent. Par exemple, `ToolErrorMiddleware` vient avant `ToolRetryMiddleware` : le retry est tenté d'abord, et l'erreur n'est convertie en message qu'à la fin.

### 12.4 LangChain : le RAG

| Composant | Classe utilisée |
|---|---|
| Document loader | `PyPDFLoader` |
| Text splitter | `RecursiveCharacterTextSplitter` |
| Embeddings | `OpenAIEmbeddings` |
| Vector store | `PineconeVectorStore` |
| Recherche par mots-clés | `BM25Retriever` |
| Retriever personnalisé | `RerankingRetriever(BaseRetriever)` |
| Reranker | `PineconeRerank` (un `BaseDocumentCompressor`) |

### 12.5 Préférence pour l'officiel

Règle suivie tout au long du projet : **utiliser les composants officiels** (`create_agent`, les middlewares fournis, les hooks documentés, les savers et stores LangGraph) plutôt que du code maison. On écrit du code maison seulement quand rien n'existe, et on l'écrit alors sous la forme d'une extension officielle (un middleware, un `BaseRetriever`, une règle d'édition de contexte).

---

## 13. Qualité et méthode de travail

- **Tests :** environ 730 tests backend (pytest) et 346 tests frontend (vitest), plus des parcours réels automatisés avec Playwright.
- **QA fondée sur des preuves :** un statut « completed » ne prouve pas la qualité. Chaque vérification compare la réponse à la vraie sortie des outils.
- **Mesurer avant de décider :** le RAG hybride a été adopté sur benchmark, d'autres idées ont été rejetées par la mesure, et les seuils de la recherche sémantique ont été calibrés sur des scores réels.
- **Méthode :**
  - un spec, puis un plan ;
  - du TDD (le test échoue d'abord, puis il passe) ;
  - un commit par étape ;
  - une revue de code finale ;
  - un essai en conditions réelles.
- **Documentation vivante :** `CLAUDE.md` décrit l'architecture, `docs/TOOLS.md` le registre des outils, `docs/VOICE.md` la voix. Les specs et plans sont dans `docs/superpowers/`.

---

## 14. Technologies utilisées

| Domaine | Technologies |
|---|---|
| Agents | LangChain 1.4, LangGraph 1.2, langchain-mcp-adapters |
| Modèles | OpenAI (gpt-4o-mini, text-embedding-3-small, omni-moderation, GPT-Live), Anthropic Claude en secours |
| Données | SQLite, Pinecone, BM25, Yahoo Finance, Tavily |
| Protocoles | MCP, AG-UI, SSE, WebRTC, WebSocket |
| Backend | Python, FastAPI, uv, pydantic-settings |
| Frontend | React, TypeScript, Vite, Tailwind, CopilotKit, react-router |
| Cloud | AWS Bedrock AgentCore (Runtime, Gateway, Memory, Browser), Lambda, SES, Cognito, Secrets Manager, CloudWatch |
| IaC / CI-CD | AWS CDK (Python), Docker, GitHub Actions + OIDC |
| Tests | pytest, vitest, Testing Library, Playwright |

---

## 15. Les concepts essentiels à retenir

1. **Le multi-agents en superviseur :** un routeur qui délègue à des spécialistes, chacun dans son sous-graphe.
2. **MCP :** brancher des outils externes avec un protocole standard, en local comme en production.
3. **Human-in-the-Loop :** `interrupt` puis `resume`, avec un état durable qui survit aux redémarrages.
4. **Les middlewares :** ajouter sécurité, fiabilité et gestion du contexte sans toucher aux agents.
5. **Le RAG hybride avec reranking :** le sens, les mots-clés et un reclassement, choisis par la mesure.
6. **La fenêtre de contexte :** maîtriser le coût et la latence des longues conversations.
7. **Mémoire courte et mémoire longue :** checkpointer et store, plus la recherche sémantique.
8. **Generative UI :** un agent qui affiche des composants, pas seulement du texte (AG-UI).
9. **Le calcul déterministe hors du LLM :** des chiffres exacts même avec un petit modèle.
10. **Des garde-fous en couches :** chaque risque est couvert plusieurs fois.
11. **Une QA fondée sur des preuves :** vérifier le fond, pas le statut.
12. **La production :** infrastructure en code, déploiement OIDC sans clé, versions épinglées.
