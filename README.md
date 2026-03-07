# Research Recommendation Agent

Reads your OneNote notes from the last N days, infers your active research
topics, searches arXiv and Semantic Scholar for recent papers, and returns
personalised top-3 picks with explanations — every week.

---

## Architecture

```
firstagenticworkflow/
├── auth/
│   └── graph_auth.py        # Microsoft Graph OAuth (MSAL Device Code Flow)
├── connectors/
│   └── onenote.py           # Fetch OneNote pages via Graph API
├── agents/
│   ├── context_summarizer.py  # Claude: notes → structured research profile
│   ├── paper_retriever.py     # arXiv + Semantic Scholar search
│   ├── ranker.py              # TF-IDF Stage 1 + Claude LLM Stage 2 reranker
│   └── presenter.py           # Format digest (terminal / markdown / dict)
├── storage/
│   └── db.py                # SQLite: paper history, runs, feedback
├── main.py                  # CLI entry point
├── app.py                   # Streamlit UI
├── config.py                # Centralised settings from .env
├── requirements.txt
└── .env.example
```

---

## Quick start

### 1. Clone and install

```bash
cd firstagenticworkflow
pip install -r requirements.txt
```

### 2. Create your `.env` file

```bash
cp .env.example .env
```

Fill in the values (see below for how to get each one).

### 3. Test without OneNote (dry run)

```bash
# CLI — uses built-in sample notes, no Microsoft login required
python main.py --dry-run

# Streamlit UI
streamlit run app.py
# Then tick "Dry run" in the sidebar
```

### 4. Full run with your OneNote

```bash
python main.py
```

The first run opens a Microsoft sign-in prompt in your browser (Device Code Flow).
After sign-in the token is cached in `.msal_token_cache.json` for future runs.

---

## Getting your API keys

### Microsoft Azure (required for OneNote)

1. Go to [portal.azure.com](https://portal.azure.com)
2. Search for **App registrations** → **New registration**
3. Name it anything (e.g. `research-agent`), choose **Accounts in any tenant** or
   **Personal Microsoft accounts** depending on which account your OneNote is on
4. Under **Authentication** → **Add a platform** → **Mobile and desktop applications**
   → tick `https://login.microsoftonline.com/common/oauth2/nativeclient`
5. Copy the **Application (client) ID** → `AZURE_CLIENT_ID` in your `.env`
6. Copy the **Directory (tenant) ID** → `AZURE_TENANT_ID` (or use `common`)

No client secret needed — this uses MSAL Public Client (Device Code Flow).

### Anthropic API (required)

1. Go to [console.anthropic.com](https://console.anthropic.com)
2. Create an API key
3. Set it as `ANTHROPIC_API_KEY` in your `.env`

### Semantic Scholar (optional)

Free tier works without a key (lower rate limits).
Register at [semanticscholar.org/product/api](https://www.semanticscholar.org/product/api)
and set `SEMANTIC_SCHOLAR_API_KEY` if you want higher limits.

---

## CLI usage

```bash
# Standard run — last 10 days, all notebooks
python main.py

# Custom lookback window
python main.py --lookback 7

# Restrict to a specific OneNote section (faster, less noise)
python main.py --section-id <your-section-id>

# Restrict to a specific notebook
python main.py --notebook-id <your-notebook-id>

# Dry run (sample notes, no Microsoft auth needed)
python main.py --dry-run
```

To find your section/notebook IDs, you can temporarily add this to a script:

```python
from auth.graph_auth import get_access_token
from connectors.onenote import list_notebooks, list_sections

token = get_access_token()
for nb in list_notebooks(token):
    print(nb["id"], nb["displayName"])
for sec in list_sections(token):
    print(sec["id"], sec["displayName"])
```

---

## Streamlit UI

```bash
streamlit run app.py
```

Features:
- Adjustable lookback window (sidebar slider)
- Notebook/section ID filter (optional)
- Dry run toggle
- Per-paper feedback buttons (Useful / Not relevant / Too theoretical)
- View past digests
- Download digest as JSON

---

## How the ranking works

**Stage 1 — TF-IDF scoring** (fast, no API cost):

```
score = 0.45 × semantic_relevance   (cosine similarity to your topics)
      + 0.20 × recency              (newer = higher)
      + 0.20 × novelty              (not recommended before = higher)
      + 0.15 × citation_boost       (log-scaled citation count)
```

Top 15 candidates pass to Stage 2.

**Stage 2 — Claude LLM re-ranking**:
Claude reads your research profile and the 15 candidates, selects the final
top-N, and writes a personalised explanation for each.

---

## Memory and personalisation

Every run persists to `research_agent.db` (SQLite):
- **paper_history** — URLs of all previously recommended papers (avoids duplicates next week)
- **digest_runs** — full run log with profile + output JSON
- **feedback** — your Useful / Not relevant / Too theoretical clicks

Future Phase 3 work: use feedback history to bias the ranker toward your
preferred paper types (methods vs. surveys, applied vs. theoretical).

---

## Roadmap

| Phase | What |
|-------|------|
| MVP (now) | OneNote → topics → arXiv+SS → rank → top 3 |
| Phase 2 | Crossref integration, better deduplication, Semantic Scholar enrichment |
| Phase 3 | Feedback-aware ranking, Outlook email context, Sunday auto-email |
