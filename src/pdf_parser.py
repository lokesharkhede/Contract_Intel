from unstructured.partition.pdf import partition_pdf

def parse_contract(pdf_path: str) -> list[str]:

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
