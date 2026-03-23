# Radar — Weekly Research Recommendation Agent

Reads your notes from the last week, infers your active research topics, searches arXiv and Semantic Scholar for recent papers, and delivers a personalised top-3 digest to your inbox every Saturday at 7:30 PM.

---

## How it works

1. **You write notes** in `notes.txt` — free-form text about what you're working on, studying, or building that week
2. **Claude reads your notes** and extracts a structured research profile — active topics, keywords, what to exclude
3. **Papers are fetched** from arXiv and Semantic Scholar using those keywords — up to ~60 candidates from the last 30 days
4. **TF-IDF narrows** the pool to the top 15 most relevant candidates by cosine similarity
5. **Claude re-ranks the top 15** and picks the final 3 with personalised explanations
6. **Output is saved and emailed** to your inbox — digest written to `digest.md` and sent as HTML email
7. **Task Scheduler runs it automatically** every Saturday at 7:30 PM

---

## Paper selection strategy

Every digest contains exactly **3 papers** using a deliberate split:

| Pick | Selection basis |
|------|----------------|
| **[Quality Pick]** | Citations, published venue vs preprint, author reputation — a paper you can cite with confidence |
| **[Relevance Pick] × 2** | Pure relevance to your week's work — a preprint from yesterday with 0 citations is fine |

---

## Project structure

```
firstagenticworkflow/
├── auth/
│   └── graph_auth.py           # Microsoft Graph OAuth (MSAL Device Code Flow)
├── connectors/
│   └── onenote.py              # Fetch OneNote pages via Graph API
├── agents/
│   ├── context_summarizer.py   # Claude: notes → structured ResearchProfile (Pydantic)
│   ├── paper_retriever.py      # arXiv + Semantic Scholar search → Paper (Pydantic)
│   ├── ranker.py               # TF-IDF Stage 1 + Claude Stage 2 reranker → RankedPaper
│   └── presenter.py            # Format digest (terminal / markdown / dict)
├── notifications/
│   └── email_sender.py         # Gmail SMTP HTML email sender
├── storage/
│   └── db.py                   # SQLite: paper history, digest runs, feedback
├── main.py                     # CLI entry point
├── app.py                      # Streamlit UI
├── config.py                   # All settings via environment variables
├── schedule_weekly.ps1         # Windows Task Scheduler registration script
└── requirements.txt
```

---

## Quick start

### 1. Clone and install

```powershell
git clone https://github.com/<your-username>/research-recommendation-agent.git
cd research-recommendation-agent

python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Set environment variables

Set these in **Windows System Environment Variables** (search "Environment Variables" in the Start menu). No `.env` file needed — all secrets come from system env vars.

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Always | Get from [console.anthropic.com](https://console.anthropic.com) |
| `EMAIL_SENDER` | For email | Your Gmail address |
| `EMAIL_PASSWORD` | For email | Gmail App Password (16-char) — generate at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords) |
| `EMAIL_RECIPIENT` | For email | Inbox to receive the digest (can be same as sender) |
| `AZURE_CLIENT_ID` | OneNote only | Azure app registration client ID |
| `AZURE_TENANT_ID` | OneNote only | Azure tenant ID (default: `common`) |
| `SEMANTIC_SCHOLAR_API_KEY` | Optional | Raises API rate limits |
| `LOOKBACK_DAYS` | Optional | Days of notes to read (default: 10) |
| `PAPERS_PER_TOPIC` | Optional | Candidates per keyword (default: 10) |
| `TOP_N_PAPERS` | Optional | Papers in final digest (default: 3) |

### 3. Write your notes

Create `notes.txt` in the project folder and paste your weekly notes — free-form text about what you've been working on, reading, or thinking about:

```
This week I've been working on GNN models for materials property prediction.
Studying multigrid methods for my scientific computing course.
Medical waste startup: testing object detection models for waste segregation.
Exploring diffusion models and how they compare to GANs.
Not interested in: pure NLP, web dev, anything unrelated to ML/science.
```

### 4. Run

```powershell
# Test with built-in sample notes (no setup needed)
python main.py --dry-run

# Run with your own notes, save to file
python main.py --notes-file notes.txt --output digest.md

# Run + email the digest
python main.py --notes-file notes.txt --output digest.md --email
```

---

## Scheduling (Windows Task Scheduler)

Register a weekly job that runs automatically every Saturday at 7:30 PM:

```powershell
# Open PowerShell as Administrator, then:
.\schedule_weekly.ps1
```

The task runs even if it was missed (e.g. PC was off) — it will execute on next startup.

To test the scheduled task immediately:
```powershell
Start-ScheduledTask -TaskName 'WeeklyResearchDigest'
```

To remove it:
```powershell
Unregister-ScheduledTask -TaskName 'WeeklyResearchDigest' -Confirm:$false
```

---

## CLI flags

```powershell
python main.py --dry-run                          # Use built-in sample notes
python main.py --notes-file notes.txt             # Use your notes file
python main.py --output digest.md                 # Save as Markdown
python main.py --output digest.txt                # Save as plain text
python main.py --email                            # Send digest by email
python main.py --lookback 7                       # Only read last 7 days of notes
python main.py --section-id <id>                  # Restrict to OneNote section
python main.py --notebook-id <id>                 # Restrict to OneNote notebook
```

---

## Streamlit UI

```powershell
streamlit run app.py
```

Features:
- Adjustable lookback window and paper count
- Dry run toggle
- Per-paper feedback (Useful / Not relevant / Too theoretical)
- View and compare past digests
- Download digest as JSON

---

## Ranking system

### Stage 1 — TF-IDF (fast, no API cost)

```
score = 0.45 × semantic_relevance   (cosine similarity to your topics)
      + 0.20 × recency              (1.0 today → 0.0 at 30 days)
      + 0.20 × novelty              (1.0 if never recommended before)
      + 0.15 × citation_boost       (log-scaled citation count)
```

Top 15 pass to Stage 2.

### Stage 2 — Claude LLM re-ranking

Claude receives your research profile and each candidate's title, abstract, citation count, venue, publication status, and authors. It selects:
- **1 Quality Pick** — highest rigor signals (citations, published venue, strong authors)
- **2 Relevance Picks** — most directly useful to your current work, signals ignored

---

## Memory

Every run persists to `research_agent.db` (SQLite):

| Table | Purpose |
|-------|---------|
| `paper_history` | All previously recommended URLs — avoids duplicates next week |
| `digest_runs` | Full run log with profile + output JSON |
| `feedback` | Your Useful / Not relevant / Too theoretical clicks |

---

## Roadmap

| Phase | Status | What |
|-------|--------|------|
| 1 — MVP | Complete | Notes file → topics → arXiv+SS → rank → top 3 → email |
| 2 — Better retrieval | Planned | Crossref integration, h-index via Semantic Scholar author API, better deduplication |
| 3 — Agentic loop | Planned | Claude drives the search via tool use instead of fixed pipeline |
| 4 — Full assistant | Planned | Feedback-aware ranking, Outlook email context, OneNote integration |
