import fitz
from langchain.schema import Document
from pathlib import Path


def load_pdf(path: Path):
    doc = fitz.open(path)
    docs = []
    for i, page in enumerate(doc):
        text = page.get_text("text")
        docs.append(
            Document(
                page_content=text,
                metadata={"source": str(path), "page": i + 1}
            )
        )
    return docs
