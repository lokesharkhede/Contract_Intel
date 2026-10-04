"""
pdf_parser.py — turns a contract PDF into a list of clean text paragraphs.

Unstructured.io's partition_pdf() breaks a PDF into typed elements
(Title, NarrativeText, ListItem, Table, etc.) instead of one flat text blob.
For contracts we mostly care about NarrativeText/Title elements — that's
where clause language lives.
"""

from unstructured.partition.pdf import partition_pdf


def parse_contract(pdf_path: str) -> list[str]:
    """
    Returns a list of paragraph-level text chunks from the PDF.
    Each chunk is later checked against every clause type via semantic
    similarity, so we keep chunks reasonably sized (roughly one section
    or clause per chunk works best).
    """
    elements = partition_pdf(filename=pdf_path, strategy="fast")

    paragraphs = []
    for el in elements:
        text = str(el).strip()
        if len(text) < 15:
            # skip stray headers/footers/page numbers — too short to be a clause
            continue
        paragraphs.append(text)

    return paragraphs


if __name__ == "__main__":
    import sys
    paras = parse_contract(sys.argv[1])
    for i, p in enumerate(paras):
        print(f"[{i}] {p[:120]}")
