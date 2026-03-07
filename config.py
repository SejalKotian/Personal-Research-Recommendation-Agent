import os
from dotenv import load_dotenv

load_dotenv()

# --- Microsoft Graph ---
# These are only required for real OneNote runs, not dry-run mode.
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "common")

# Microsoft Graph scopes needed for OneNote (delegated auth only — no app-only support)
GRAPH_SCOPES = ["Notes.Read", "User.Read", "offline_access"]
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

# --- Anthropic ---
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
CLAUDE_MODEL = "claude-sonnet-4-6"

# --- Semantic Scholar ---
SEMANTIC_SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")

# --- App settings ---
LOOKBACK_DAYS = int(os.getenv("LOOKBACK_DAYS", 10))
PAPERS_PER_TOPIC = int(os.getenv("PAPERS_PER_TOPIC", 10))
TOP_N_PAPERS = int(os.getenv("TOP_N_PAPERS", 3))

# Token cache file (MSAL persistent cache)
TOKEN_CACHE_PATH = os.path.join(os.path.dirname(__file__), ".msal_token_cache.json")

# SQLite DB path
DB_PATH = os.path.join(os.path.dirname(__file__), "research_agent.db")
