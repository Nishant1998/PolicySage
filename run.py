from pathlib import Path

from app.core.logging import configure_logging
from app.rag.vectorstore import index_document_chunks
from app.services.ingestion import chunk_documents, load_file, load_metadata

if __name__ == "__main__":
    configure_logging()
    base_dir = Path(__file__).resolve().parent
    file_path = base_dir / "data/kb/health/star_health/star_health_super_star_9b9e4ae7.pdf"
    # Read catalogue metadata and attach it to the loaded pages.
    metadata = load_metadata(file_path, base_dir / "data/kb/metadata.csv")

    documents = load_file(file_path)
    for document in documents:
        document.metadata.update(metadata)
    print(f"Loaded pages/sections: {len(documents)}")
    for number, document in enumerate(documents, start=1):
        print(f"\nPage/section {number}")
        print(document.page_content)

    # Split the document and print each chunk for inspection.
    chunks = chunk_documents(documents)
    print(f"\nChunks: {len(chunks)}")
    for number, chunk in enumerate(chunks, start=1):
        print(f"\nChunk {number}")
        print(chunk.page_content)

    # Use the configured APIs to embed and upload chunks to Pinecone.
    chunk_ids = index_document_chunks(chunks)
    print(f"\nIndexed chunks: {len(chunk_ids)}")
