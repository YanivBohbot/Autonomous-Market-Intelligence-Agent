import json
from pathlib import Path


_KB_MANIFEST_PATH = Path(__file__).parent.parent / "tools" / "kb_documents.json"

# RAG_SYSTEM_PROMPT and SUPERVISOR_ROUTING_PROMPT embed this literal token
# instead of an f-string-interpolated document list: a PDF uploaded via
# app/api/routers/data.py's /data/import/pdf while the server is already
# running (app/data_import/pdf_ingest.py) must be visible to the research
# specialist and the routing supervisor immediately, not only after a
# restart. Callers substitute ingested_documents_list()'s fresh read in at
# call time -- see app.agent.middleware.fresh_documents_prompt (rag_agent)
# and supervisor.py's routing call (manual substitution, no middleware).
INGESTED_DOCUMENTS_PLACEHOLDER = "{INGESTED_DOCUMENTS}"


def ingested_documents_list() -> str:
    try:
        docs = sorted(json.loads(_KB_MANIFEST_PATH.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return "none ingested yet"
    return ", ".join(docs) if docs else "none ingested yet"
