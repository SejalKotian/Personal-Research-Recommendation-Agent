# Research Recommendation Agent

Weekly AI pipeline: reads OneNote notes → extracts research topics via Claude → searches arXiv + Semantic Scholar → ranks by TF-IDF + LLM reranker → returns top 3 personalised paper picks.

## Project structure

```
firstagenticworkflow/
├── auth/graph_auth.py          # MSAL Device Code Flow for Microsoft Graph
├── connectors/onenote.py       # OneNote page fetcher via Graph API
├── agents/context_summarizer.py  # Claude: notes → ResearchProfile (Pydantic)
├── agents/paper_retriever.py   # arXiv + Semantic Scholar search → Paper (Pydantic)
├── agents/ranker.py            # TF-IDF Stage 1 + Claude Stage 2 reranker → RankedPaper
├── agents/presenter.py         # format_terminal / format_markdown / format_dict
├── storage/db.py               # SQLite: paper_history, digest_runs, feedback tables
├── main.py                     # CLI orchestrator
├── app.py                      # Streamlit UI
├── config.py                   # All settings via environment variables
└── requirements.txt
```

## Environment variables (set in Windows System Environment Variables)

- `ANTHROPIC_API_KEY` — required for all runs
- `AZURE_CLIENT_ID` — required for real OneNote runs only
- `AZURE_TENANT_ID` — required for real OneNote runs only (default: "common")
- `SEMANTIC_SCHOLAR_API_KEY` — optional, raises rate limits
- `LOOKBACK_DAYS` — default 10
- `PAPERS_PER_TOPIC` — default 10
- `TOP_N_PAPERS` — default 3
- `EMAIL_SENDER` — Gmail address to send from (e.g. you@gmail.com)
- `EMAIL_PASSWORD` — Gmail App Password (16-char, not real password)
- `EMAIL_RECIPIENT` — address to receive the digest (can be same as sender)

Never use a `.env` file — all secrets come from system environment variables.

## Virtual environment

```powershell
agaivenv2\Scripts\activate
```

## Common commands

```powershell
# Test without Microsoft auth (uses built-in sample notes)
python main.py --dry-run

# Run from a local notes file (no Microsoft auth needed)
python main.py --notes-file notes.txt --output digest.md

# Run + save + email digest
python main.py --notes-file notes.txt --output digest.md --email

# Full run with real OneNote (requires AZURE_CLIENT_ID set)
python main.py

# Custom lookback
python main.py --lookback 7

# Restrict to a specific OneNote section
python main.py --section-id <id>

# Streamlit UI
streamlit run app.py

# Register weekly Sunday 7pm Task Scheduler job (run once as Admin)
.\schedule_weekly.ps1
```

## Tech stack

- Python 3.13, MSAL, Anthropic SDK (claude-sonnet-4-6), scikit-learn TF-IDF
- Streamlit, SQLite, arXiv API, Semantic Scholar API
- Microsoft Graph for OneNote (delegated auth only — no app-only support)

## Key design decisions

- `config.py` uses `os.getenv()` for Azure keys (optional) and `os.environ[]` for Anthropic key (required)
- Azure keys are validated lazily in `auth/graph_auth.py` only when OneNote is actually called
- `load_dotenv()` in config.py is a no-op if system env vars are already set (system vars always win)
- TF-IDF narrows candidates to top 15, then Claude re-ranks and writes explanations for top N
- SQLite stores paper history to avoid recommending duplicates across weekly runs

## Current status

Phase 1 MVP complete. Blocked on Anthropic credits propagating (credits purchased, key verified, awaiting activation).

## Roadmap

- Phase 2: Crossref integration, better deduplication
- Phase 3: Outlook email context, feedback-aware ranking, Sunday auto-email
