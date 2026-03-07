"""
Ranker

Two-stage ranking:
  Stage 1 — TF-IDF cosine similarity between the user's research profile
             and each candidate paper's title + abstract.
  Stage 2 — Claude LLM re-ranks the top-K candidates and writes a
             personalised explanation for each of the final top-N papers.

Scoring formula (Stage 1):
  Final Score = 0.45 × semantic_relevance + 0.20 × recency + 0.20 × novelty
              + 0.15 × citation_boost

  novelty = 1.0 if paper hasn't been seen before (not in history)
  citation_boost = log1p(citation_count) / log1p(1000) capped at 1.0
"""

import json
import math
import re
from datetime import datetime, timezone
from typing import Optional
import anthropic
from pydantic import BaseModel
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import config
from agents.context_summarizer import ResearchProfile
from agents.paper_retriever import Paper


class RankedPaper(BaseModel):
    paper: Paper
    score: float
    relevance_label: str          # "research" | "coursework" | "project"
    explanation: str              # LLM-generated 2-3 sentence explanation
    read_depth: str               # "skim (10 min)" | "deep read" | "save for later"


# ─── Stage 1: TF-IDF Scoring ──────────────────────────────────────────────────

def _recency_score(date_str: str) -> float:
    """
    Returns 1.0 for today, decaying to 0.0 at 30 days ago.
    """
    if not date_str:
        return 0.5
    try:
        pub_date = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - pub_date).days
        return max(0.0, 1.0 - age_days / 30.0)
    except ValueError:
        return 0.5


def _citation_boost(citation_count: Optional[int]) -> float:
    if citation_count is None:
        return 0.0
    return min(1.0, math.log1p(citation_count) / math.log1p(1000))


def _build_query_doc(profile: ResearchProfile) -> str:
    parts = profile.active_topics + profile.keywords + profile.current_tasks
    return " ".join(parts)


def tfidf_rank(
    profile: ResearchProfile,
    papers: list[Paper],
    seen_paper_urls: set[str],
    top_k: int = 15,
) -> list[tuple[Paper, float]]:
    """
    Return (paper, score) pairs sorted descending, top_k items.
    """
    if not papers:
        return []

    query_doc = _build_query_doc(profile)
    paper_docs = [f"{p.title} {p.abstract}" for p in papers]

    vectorizer = TfidfVectorizer(stop_words="english", max_features=10000)
    all_docs = [query_doc] + paper_docs
    tfidf_matrix = vectorizer.fit_transform(all_docs)

    query_vec = tfidf_matrix[0]
    paper_vecs = tfidf_matrix[1:]
    similarities = cosine_similarity(query_vec, paper_vecs)[0]

    scored = []
    for i, paper in enumerate(papers):
        semantic = float(similarities[i])
        recency = _recency_score(paper.date)
        novelty = 0.0 if paper.url in seen_paper_urls else 1.0
        citation = _citation_boost(paper.citation_count)

        score = (
            0.45 * semantic
            + 0.20 * recency
            + 0.20 * novelty
            + 0.15 * citation
        )
        scored.append((paper, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


# ─── Stage 2: LLM Re-ranker ───────────────────────────────────────────────────

_RERANK_SYSTEM = """\
You are a research assistant helping a graduate student discover the most \
relevant recent papers for their specific work.

Given:
1. A JSON research profile describing their active topics, tasks, and keywords
2. A numbered list of candidate papers (title + abstract)

Your job is to:
- Select the top {n} papers most useful to this person RIGHT NOW
- For each selected paper, write a 2-3 sentence explanation of why it matters
  to them specifically (reference their actual topics/tasks)
- Assign a relevance_label: one of "research", "coursework", or "project"
- Assign a read_depth: one of "skim (10 min)", "deep read", or "save for later"

Output ONLY valid JSON (no markdown fences):
[
  {{
    "index": <1-based index from the candidate list>,
    "relevance_label": "...",
    "explanation": "...",
    "read_depth": "..."
  }},
  ...
]
"""


def llm_rerank(
    profile: ResearchProfile,
    candidates: list[tuple[Paper, float]],
    top_n: int = config.TOP_N_PAPERS,
) -> list[RankedPaper]:
    """
    Send top-K TF-IDF candidates to Claude for final re-ranking + explanation.
    Returns the final top_n RankedPapers.
    """
    if not candidates:
        return []

    profile_json = profile.model_dump_json(indent=2)

    # Build numbered candidate list
    candidate_lines = []
    for i, (paper, score) in enumerate(candidates, start=1):
        candidate_lines.append(
            f"{i}. Title: {paper.title}\n"
            f"   Date: {paper.date} | Source: {paper.source}\n"
            f"   Abstract: {paper.abstract[:500]}..."
        )
    candidates_text = "\n\n".join(candidate_lines)

    system_prompt = _RERANK_SYSTEM.format(n=top_n)

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    message = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=2048,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Research Profile:\n{profile_json}\n\n"
                    f"Candidate Papers:\n{candidates_text}\n\n"
                    f"Select and explain the top {top_n} papers for this researcher."
                ),
            }
        ],
    )

    raw = message.content[0].text.strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    selections = json.loads(raw)

    results = []
    for sel in selections[:top_n]:
        idx = int(sel["index"]) - 1
        if idx < 0 or idx >= len(candidates):
            continue
        paper, score = candidates[idx]
        results.append(
            RankedPaper(
                paper=paper,
                score=score,
                relevance_label=sel.get("relevance_label", "research"),
                explanation=sel.get("explanation", ""),
                read_depth=sel.get("read_depth", "skim (10 min)"),
            )
        )

    return results


# ─── Public interface ─────────────────────────────────────────────────────────

def rank_papers(
    profile: ResearchProfile,
    papers: list[Paper],
    seen_paper_urls: set[str],
    top_n: int = config.TOP_N_PAPERS,
) -> list[RankedPaper]:
    """
    Full two-stage ranking pipeline.
    """
    # Stage 1: TF-IDF narrowing
    tfidf_top = tfidf_rank(profile, papers, seen_paper_urls, top_k=min(15, len(papers)))

    if not tfidf_top:
        return []

    # Stage 2: LLM re-ranking
    return llm_rerank(profile, tfidf_top, top_n=top_n)
