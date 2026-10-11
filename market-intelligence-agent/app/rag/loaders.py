from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document


def load_pdf(path: str, *, filename: str, source: str | None = None) -> list[Document]:
    """Document Loader: one Document per PDF page (0-based `page` metadata).

    `source` overrides metadata["source"] when the loader's own value is not
    stable -- e.g. the upload path's randomized tempfile name. Chunk IDs
    derive from it, so an unstable source would duplicate vectors on
    re-upload. `filename` is accepted for the caller's readability; the
    ingestion step stamps metadata["filename"] on each split."""
    documents = PyPDFLoader(path).load()
    if source is not None:
        for doc in documents:
            doc.metadata["source"] = source
    return documents
