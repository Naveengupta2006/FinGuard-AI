"""Policy PDFs -> section-wise chunks (document, section, page metadata) -> ChromaDB."""
import re
import sys
from pathlib import Path

try:
    import pymupdf
except ImportError:  # purane versions
    import fitz as pymupdf
import chromadb

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.append(str(PROJECT_ROOT / "src" / "rag"))
from embeddings import embed  # noqa: E402

POLICY_DIR = PROJECT_ROOT / "docs" / "risk_policies"
CHROMA_DIR = PROJECT_ROOT / "data" / "chroma"
COLLECTION = "risk_policies"

# "3.1 Review Deadlines": number + Capital-letter title, poori line, koi full stop nahi
HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+([A-Z][^.]{2,80})$")
TITLE_RE = re.compile(r"^(.*?)\s*\(([A-Z]{2,4}(?:-[A-Z]{2,4})?-\d{3})\)")
FOOTER_MARK = "FICTIONAL - FOR EDUCATIONAL USE"


def _blocks(page):
    """Page ke text blocks (upar se neeche), footer hata kar."""
    out = []
    for b in sorted(page.get_text("blocks"), key=lambda b: (round(b[1]), b[0])):
        text = " ".join(b[4].split())
        if text and FOOTER_MARK not in text:
            out.append(text)
    return out


def parse_pdf(path: Path) -> list:
    """Ek PDF ko section chunks mein todta hai. Section pages ke beech mein bhi chal sakta hai."""
    doc = pymupdf.open(path)
    doc_title, doc_id = path.stem.replace("_", " ").title(), path.stem.upper()
    chunks, current, header = [], None, []

    for page_no, page in enumerate(doc, start=1):
        for text in _blocks(page):
            h = HEADING_RE.match(text)
            if h:
                if current:
                    chunks.append(current)
                current = {"section_number": h.group(1),
                           "section": f"{h.group(1)} {h.group(2)}",
                           "paras": [], "pages": {page_no}}
            elif current is not None:
                current["paras"].append(text)
                current["pages"].add(page_no)
            else:
                header.append(text)   # pehle heading se pehle ka text = title/version
    if current:
        chunks.append(current)

    # Lamba title do blocks mein toot sakta hai, isliye header ko jod kar parse karo
    m = TITLE_RE.match(" ".join(header))
    if m:
        doc_title, doc_id = m.group(1).strip(), m.group(2)

    result = []
    for c in chunks:
        body = " ".join(c["paras"]).strip()
        if not body:   # sirf parent heading, body nahi: chunk mat banao
            continue
        result.append({
            "text": body,
            "metadata": {
                "doc_id": doc_id, "doc_title": doc_title, "file": path.name,
                "section": c["section"], "section_number": c["section_number"],
                "page_start": min(c["pages"]), "page_end": max(c["pages"]),
            },
        })
    return result


def parse_all() -> list:
    chunks = []
    for pdf in sorted(POLICY_DIR.glob("*.pdf")):
        chunks.extend(parse_pdf(pdf))
    return chunks


def main():
    chunks = parse_all()
    if not chunks:
        raise SystemExit(f"Koi PDF/chunk nahi mila: {POLICY_DIR}")

    # Retrieval ke liye embed hone wala text: doc + section context ke saath
    docs_for_embedding = [
        f"{c['metadata']['doc_title']} - {c['metadata']['section']}. {c['text']}" for c in chunks
    ]
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        client.delete_collection(COLLECTION)   # dobara chalana safe (idempotent)
    except Exception:
        pass
    col = client.create_collection(COLLECTION, metadata={"hnsw:space": "cosine"},
                                  embedding_function=None)
    col.add(
        ids=[f"{c['metadata']['doc_id']}::{c['metadata']['section_number']}" for c in chunks],
        documents=[c["text"] for c in chunks],
        metadatas=[c["metadata"] for c in chunks],
        embeddings=embed(docs_for_embedding),
    )

    print(f"Ingested {len(chunks)} chunks from {len(list(POLICY_DIR.glob('*.pdf')))} PDFs into '{COLLECTION}'")
    for c in chunks[:4]:
        m = c["metadata"]
        print(f"  {m['doc_id']} | {m['section']} | pages {m['page_start']}-{m['page_end']} | {len(c['text'])} chars")


if __name__ == "__main__":
    main()