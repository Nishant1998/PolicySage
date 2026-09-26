from functools import lru_cache

from langchain_core.documents import Document

from app.core.observability import traced_operation


MAX_PAGES = 400


@lru_cache(maxsize=1)
def converter():
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    return DocumentConverter(format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=PdfPipelineOptions(document_timeout=600)),
    })


@traced_operation("parse_pdf")
def parse_pdf(path, source):
    from docling.datamodel.base_models import ConversionStatus

    result = converter().convert(path, max_num_pages=MAX_PAGES, raises_on_error=False)
    total_pages = result.input.page_count
    if not 0 < total_pages <= MAX_PAGES:
        raise ValueError(f"Use a readable, unlocked PDF with 1 to {MAX_PAGES} pages.")
    if result.status != ConversionStatus.SUCCESS:
        raise ValueError("Docling could not fully convert this PDF.")

    documents = []
    for page in range(1, total_pages + 1):
        markdown = result.document.export_to_markdown(page_no=page, traverse_pictures=True)
        text = markdown.replace("<!-- image -->", "").strip()
        if text:
            documents.append(Document(page_content=text, metadata={"source": source, "page": page}))
    if not documents:
        raise ValueError("No readable PDF text was extracted.")
    return documents, total_pages
