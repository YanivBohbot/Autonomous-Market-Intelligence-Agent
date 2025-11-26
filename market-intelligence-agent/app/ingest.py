import os
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore
from app.core.config import settings


def ingest_document():
    """

    Read PDF from data folder et index in pinecone
    """
    print(" Starting to ingest to pinecone....")

    data_folder = "data"
    documents = []

    if not os.path.exists(data_folder):
        os.makedirs(data_folder)
        print(f"⚠️ Folder '{data_folder}' created. Put some PDFs and restar.")
        return

    for file in os.listdir(data_folder):
        if file.endswith(".pdf"):
            pdf_path = os.path.join(data_folder, file)
            print(f" Charge the {file}..")
            loader = PyPDFLoader(pdf_path)
            documents.extend(loader.load())

    if not documents:
        print("❌ No document PDF found.")
        return

    text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)

    splits = text_splitter.split_documents(documents)
    print(f"✂️ Documents découpés en {len(splits)} chunks.")

    print("cw Stockage dans Pinecone (cela peut prendre quelques secondes)...")

    embeddings = OpenAIEmbeddings(model=settings.OPENAI_EMBEDDING_MODEL)

    PineconeVectorStore.from_documents(
        documents=splits, embedding=embeddings, index_name=settings.PINECONE_INDEX_NAME
    )


print("✅ Ingestion  finish ! Base Knowledge ready .")


if __name__ == "__main__":
    ingest_document()
