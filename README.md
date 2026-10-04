# Contract Intelligence & Redline Assistant

An agentic pipeline that reads a contract PDF, matches its clauses against a
configurable risk playbook, and produces a grounded, LLM-reasoned risk report
— with results persisted so you can review history and chat with past
contracts later.

📄 **Full write-up (problem statement, design reasoning, architecture
diagrams, code-to-concept mapping): [`DOCUMENTATION.md`](./DOCUMENTATION.md)**

## How it works, in one paragraph

Unstructured.io parses the PDF into paragraphs → cosine similarity over
sentence embeddings matches each paragraph to a clause type from
`playbook.yaml` → regex/NER/fuzzy matching extracts concrete evidence (day
counts, dates, jurisdiction candidates) from the matched text → Gemini reads
the playbook rule plus that evidence (never the raw contract) and returns a
risk verdict with a citation → a guardrail checks that citation is actually
grounded in the extracted evidence before trusting it, falling back to a
deterministic threshold check otherwise → LangGraph orchestrates all of this
as a state graph → results persist to SQLite → Streamlit is the front end.

## Folder structure

```
contract_intel/
├── DOCUMENTATION.md               # Full technical write-up + diagrams
├── playbook.yaml                  # The 10 clause rules (edit this to change risk logic)
├── requirements.txt
├── generate_sample_contracts.py   # One-off script that made the 5 sample PDFs
├── app.py                         # Streamlit frontend — the only file you "run"
│
├── data/
│   ├── contracts/                 # Sample input PDFs (2 clean, 3 with injected defects)
│   └── contract_intel.db          # SQLite database — created automatically on first run
│
└── src/
    ├── config.py                  # Model names, thresholds, file paths — one place to tune
    ├── pdf_parser.py               # Unstructured.io wrapper: PDF -> list of paragraphs
    ├── nlp_utils.py                # Embeddings (cosine similarity), spaCy NER, regex, fuzzy match,
    │                                 evidence extraction for the LLM reconciliation step
    ├── playbook_engine.py         # Deterministic rules + reconcile_contract() orchestration
    │                                 + the grounding guardrail against LLM hallucination
    ├── llm_client.py              # Gemini wrapper — reconcile_clause() makes the risk call,
    │                                 grounded in evidence; other functions only narrate
    ├── memory.py                  # SQLite persistence layer (the "memory" in the stack)
    └── graph.py                   # LangGraph state graph wiring all of the above together
```

## Setup

```bash
pip install -r requirements.txt
python -m spacy download en_core_web_sm
python generate_sample_contracts.py     # only needed once, PDFs already included
export GEMINI_API_KEY="your-key-here"
streamlit run app.py
```

## How to use it

1. Go to the **Review a Contract** tab, upload one of the PDFs from
   `data/contracts/`, and click **Run Review**.
2. Try `clean_msa.pdf` first — it should come back with zero flags.
3. Try `defect_msa_liability.pdf` — it should flag the liability cap
   (0.5x instead of the 1.0x minimum) and the missing carve-outs clause.
4. Go to the **Review History** tab to see everything you've reviewed,
   and ask a question like *"What's the termination notice period?"* —
   the answer is grounded in the stored extraction, not a fresh PDF read.

## Design principles (see `DOCUMENTATION.md` for the full reasoning)

- **Retrieval, extraction, and judgment are separate steps.** Cosine
  similarity finds the right paragraph; regex/NER extracts facts; the LLM
  judges risk. No single step is asked to do more than one of these jobs.
- **The LLM must show its work.** Every risk verdict from Gemini includes a
  `cited_value` — the exact piece of evidence it relied on — and a guardrail
  verifies that citation is real before the verdict is trusted.
- **Hallucination has a bounded blast radius.** If the LLM's citation doesn't
  check out, that one clause silently falls back to a plain deterministic
  threshold check — a bad LLM output degrades gracefully instead of silently
  passing through.
