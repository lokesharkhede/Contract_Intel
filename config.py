import os
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PLAYBOOK_PATH = os.path.join(BASE_DIR, "playbook.yaml")
DB_PATH = os.path.join(BASE_DIR, "data", "contract_intel.db")
CONTRACTS_DIR = os.path.join(BASE_DIR, "data", "contracts")

# --- Gemini API ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite")

# --- Embedding Model ---
EMBEDDING_MDOEL = 'all-MiniLM-L6-v2'

# --- Semantic matching threshold ---
# Cosine similarity below this means "this paragraph probably isn't this clause type"
CLAUSE_MATCH_THRESHOLD = 0.45

# --- Fuzzy matching threshold (0-100) for jurisdiction / categorical text checks ---
FUZZY_MATCH_THRESHOLD = 80
