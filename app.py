"""
Streamlit UI — run with:

    streamlit run app.py
"""

import json
import streamlit as st

import config
from storage.db import init_db, get_seen_urls, save_recommended_papers, log_digest_run, get_recent_runs, get_run_digest, save_feedback
from connectors.onenote import get_pages_text, list_notebooks, list_sections
from agents.context_summarizer import extract_research_profile
from agents.paper_retriever import retrieve_papers
from agents.ranker import rank_papers
from agents.presenter import format_markdown, format_dict
from auth.graph_auth import get_access_token

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Research Digest Agent",
    page_icon="",
    layout="wide",
)

init_db()

# ── Sidebar ───────────────────────────────────────────────────────────────────
st.sidebar.title("Research Digest Agent")
st.sidebar.markdown("Reads your OneNote notes and recommends recent papers.")

st.sidebar.divider()
st.sidebar.subheader("Settings")

lookback = st.sidebar.slider("Days to look back", min_value=3, max_value=21, value=config.LOOKBACK_DAYS)
top_n = st.sidebar.slider("Papers to recommend", min_value=1, max_value=5, value=config.TOP_N_PAPERS)
dry_run = st.sidebar.checkbox("Dry run (use sample notes)", value=False)

# Optional notebook/section filter
st.sidebar.divider()
st.sidebar.subheader("OneNote Filters (optional)")
notebook_id_input = st.sidebar.text_input("Notebook ID", placeholder="Leave blank for all notebooks")
section_id_input = st.sidebar.text_input("Section ID", placeholder="Leave blank for all sections")

notebook_id = notebook_id_input.strip() or None
section_id = section_id_input.strip() or None

st.sidebar.divider()
st.sidebar.subheader("Past Runs")
past_runs = get_recent_runs(limit=5)
if past_runs:
    run_options = {f"Run #{r['id']} — {r['run_at'][:16]}": r["id"] for r in past_runs}
    selected_run_label = st.sidebar.selectbox("View a past digest", ["(current run)"] + list(run_options.keys()))
else:
    selected_run_label = "(current run)"
    st.sidebar.caption("No past runs yet.")

# ── Main area ─────────────────────────────────────────────────────────────────
st.title("Weekly Research Digest")

# Show a past run if selected
if selected_run_label != "(current run)" and past_runs:
    run_id = run_options[selected_run_label]
    past_digest = get_run_digest(run_id)
    if past_digest:
        st.info(f"Showing archived digest from {past_digest.get('generated_at', '')[:16]}")
        st.markdown(f"> {past_digest.get('context_summary', '')}")
        for p in past_digest.get("papers", []):
            with st.expander(f"{p['rank']}. {p['title']}"):
                st.markdown(f"**{p['relevance_label'].capitalize()}** | {p['read_depth']} | {p['date']}")
                st.markdown(p["explanation"])
                st.markdown(f"[Read paper]({p['url']})")
    st.stop()

# ── Run button ────────────────────────────────────────────────────────────────
col1, col2 = st.columns([2, 1])
with col1:
    run_clicked = st.button("Analyze last {lookback} days and recommend papers".format(lookback=lookback), type="primary", use_container_width=True)

if not run_clicked:
    st.markdown(
        """
        ### How it works
        1. **Reads** your OneNote daily notes from the last N days
        2. **Extracts** your active research topics, tasks, and keywords using Claude
        3. **Searches** arXiv and Semantic Scholar for recent papers (last 30 days)
        4. **Ranks** papers by relevance to your week using TF-IDF + Claude re-ranking
        5. **Presents** the top picks with personalised explanations

        Click the button above to start. If this is your first run, you will be
        prompted to sign in to your Microsoft account.
        """
    )
    st.stop()

# ── Pipeline execution ────────────────────────────────────────────────────────
progress_bar = st.progress(0)
status = st.empty()

SAMPLE_NOTES = [
    {
        "id": "sample-1",
        "title": "Monday TODO",
        "created": "2026-02-24",
        "modified": "2026-02-24",
        "text": (
            "Working on GNN model for materials property prediction. "
            "Need to read more about spectral graph convolutions. "
            "Finish scientific computing homework on finite element methods. "
            "Customer discovery call for medical waste startup — segregation using CV. "
            "Look into Bayesian optimization for hyperparameter tuning."
        ),
    },
    {
        "id": "sample-2",
        "title": "Wednesday Research Notes",
        "created": "2026-02-26",
        "modified": "2026-02-26",
        "text": (
            "Read the DiffSBDD paper — structure-based drug design with diffusion. "
            "Interesting connection to my materials work. "
            "Coursework: PDE solvers, multigrid methods, sparse linear systems. "
            "Debug GNN attention pooling layer — NaN in gradients issue. "
            "Not relevant: pure clinical trials, wet lab biology papers."
        ),
    },
    {
        "id": "sample-3",
        "title": "Friday Startup + Research",
        "created": "2026-02-28",
        "modified": "2026-02-28",
        "text": (
            "Medical waste segregation: tested YOLOv8 on small dataset. Need more data. "
            "Consider multimodal sensing (vision + weight). "
            "GNN: switching to PyG, MessagePassing base class is cleaner. "
            "Internship prep: review system design basics, LLM fine-tuning workflows."
        ),
    },
]

try:
    # Step 1 — Fetch notes
    status.info("Step 1/4 — Fetching OneNote pages...")
    progress_bar.progress(10)

    if dry_run:
        pages = SAMPLE_NOTES
        st.caption("Dry run: using built-in sample notes.")
    else:
        pages = get_pages_text(
            lookback_days=lookback,
            section_id=section_id,
            notebook_id=notebook_id,
        )

    if not pages:
        status.error("No OneNote pages found. Try increasing the lookback window or check your notebook settings.")
        st.stop()

    progress_bar.progress(25)

    # Step 2 — Profile
    status.info("Step 2/4 — Extracting research profile with Claude...")
    profile = extract_research_profile(pages)
    progress_bar.progress(45)

    # Step 3 — Retrieve
    status.info("Step 3/4 — Searching recent papers...")
    search_keywords = profile.keywords[:6]
    candidates = retrieve_papers(search_keywords, papers_per_keyword=config.PAPERS_PER_TOPIC)
    progress_bar.progress(70)

    if not candidates:
        status.error("No papers found for your topics. Try different keywords.")
        st.stop()

    # Step 4 — Rank
    status.info("Step 4/4 — Ranking papers with Claude...")
    seen_urls = get_seen_urls()
    ranked = rank_papers(profile, candidates, seen_paper_urls=seen_urls, top_n=top_n)
    progress_bar.progress(95)

    # Persist
    digest_dict = format_dict(profile, ranked)
    log_digest_run(profile.model_dump(), digest_dict, lookback)
    save_recommended_papers(
        [
            {
                "url": rp.paper.url,
                "arxiv_id": rp.paper.arxiv_id,
                "title": rp.paper.title,
                "date": rp.paper.date,
                "source": rp.paper.source,
            }
            for rp in ranked
        ]
    )

    progress_bar.progress(100)
    status.success("Done! Here are your weekly picks.")

except Exception as e:
    status.error(f"Pipeline error: {e}")
    st.exception(e)
    st.stop()

# ── Results ───────────────────────────────────────────────────────────────────
st.divider()
st.subheader("Your week in brief")
st.markdown(f"> {profile.context_summary}")

st.subheader("Active Topics")
cols = st.columns(min(len(profile.active_topics), 3))
for i, topic in enumerate(profile.active_topics):
    cols[i % len(cols)].markdown(f"- {topic}")

st.divider()
st.subheader(f"Top {len(ranked)} Paper Picks")

for i, rp in enumerate(ranked):
    p = rp.paper
    label_color = {"research": "blue", "coursework": "green", "project": "orange"}.get(
        rp.relevance_label, "gray"
    )
    with st.expander(f"{i+1}. {p.title}", expanded=True):
        col_a, col_b, col_c = st.columns(3)
        col_a.markdown(f"**:{label_color}[{rp.relevance_label.upper()}]**")
        col_b.markdown(f"*{rp.read_depth}*")
        col_c.markdown(f"{p.date} | {p.source.replace('_', ' ').title()}")

        if p.authors:
            st.caption(", ".join(p.authors[:3]))

        st.markdown(rp.explanation)
        st.markdown(f"[Read paper]({p.url})")

        st.divider()
        feedback_col1, feedback_col2, feedback_col3, _ = st.columns([1, 1, 1, 3])
        if feedback_col1.button("Useful", key=f"useful_{i}"):
            save_feedback(p.url, "useful")
            st.toast("Marked as useful!")
        if feedback_col2.button("Not relevant", key=f"notrel_{i}"):
            save_feedback(p.url, "not_relevant")
            st.toast("Marked as not relevant.")
        if feedback_col3.button("Too theoretical", key=f"theory_{i}"):
            save_feedback(p.url, "too_theoretical")
            st.toast("Marked as too theoretical.")

# ── Export ────────────────────────────────────────────────────────────────────
st.divider()
st.download_button(
    label="Download digest as JSON",
    data=json.dumps(digest_dict, indent=2),
    file_name=f"research_digest_{digest_dict['generated_at'][:10]}.json",
    mime="application/json",
)
