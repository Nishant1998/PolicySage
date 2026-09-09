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
    import pymupdf
    from docling.datamodel.base_models import ConversionStatus

    # Use a stream so a failed open cannot retain a handle to the worker's temporary file.
    try:
        pdf = pymupdf.open(stream=path.read_bytes(), filetype="pdf")
    except pymupdf.FileDataError as exc:
        raise ValueError("Could not open the PDF. Upload a readable, unencrypted PDF.") from exc
    with pdf:
        if pdf.needs_pass or not 0 < len(pdf) <= MAX_PAGES:
            raise ValueError("Use an unlocked PDF with 1 to 400 pages.")
        native_pages = [page.get_text(sort=True).strip() for page in pdf]

    result = converter().convert(path)
    if result.status != ConversionStatus.SUCCESS:
        raise ValueError("Docling could not fully convert this PDF.")

    documents = []
    for page, native in enumerate(native_pages, 1):
        markdown = result.document.export_to_markdown(page_no=page, traverse_pictures=True)
        markdown = markdown.replace("<!-- image -->", "").strip()
        text = markdown or native
        if text:
            documents.append(Document(page_content=text, metadata={"source": source, "page": page}))
    if not documents:
        raise ValueError("No readable PDF text was extracted.")
    return documents, len(native_pages)
