"""
Paper Retriever

Searches for recent papers (last 30 days) from:
  1. arXiv API  — fast-moving ML/CS/AI preprints
  2. Semantic Scholar API — citation metadata + related-paper discovery

Returns a deduplicated list of candidate Paper objects.
"""

import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Optional
import requests
from pydantic import BaseModel

import config


class Paper(BaseModel):
    title: str
    abstract: str
    authors: list[str]
    date: str          # ISO 8601 date string (YYYY-MM-DD)
    source: str        # "arxiv" | "semantic_scholar"
    url: str
    arxiv_id: Optional[str] = None
    citation_count: Optional[int] = None
    venue: Optional[str] = None


# ─── arXiv ────────────────────────────────────────────────────────────────────

_ARXIV_API = "https://export.arxiv.org/api/query"
_ARXIV_NS = "http://www.w3.org/2005/Atom"


def _search_arxiv(query: str, max_results: int = 10) -> list[Paper]:
    """
    Query the arXiv API for papers matching `query` submitted in the last 30 days.
    arXiv API docs: https://info.arxiv.org/help/api/index.html
    """
    # Date window: last 30 days
    since = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y%m%d")
    today = datetime.now(timezone.utc).strftime("%Y%m%d")

    # arXiv search syntax: wrap multi-word queries in quotes for phrase search
    safe_query = f"ti:{query} OR abs:{query}"

    params = {
        "search_query": safe_query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }

    resp = requests.get(_ARXIV_API, params=params, timeout=20)
    resp.raise_for_status()

    root = ET.fromstring(resp.text)
    papers = []

    for entry in root.findall(f"{{{_ARXIV_NS}}}entry"):
        published_str = (
            entry.findtext(f"{{{_ARXIV_NS}}}published") or ""
        )[:10]  # YYYY-MM-DD

        # Filter to last 30 days
        if published_str and published_str < since[:4] + "-" + since[4:6] + "-" + since[6:]:
            continue

        title = (entry.findtext(f"{{{_ARXIV_NS}}}title") or "").strip().replace("\n", " ")
        abstract = (entry.findtext(f"{{{_ARXIV_NS}}}summary") or "").strip().replace("\n", " ")
        authors = [
            a.findtext(f"{{{_ARXIV_NS}}}name") or ""
            for a in entry.findall(f"{{{_ARXIV_NS}}}author")
        ]

        # Get arXiv URL and ID
        arxiv_url = ""
        arxiv_id = ""
        for link in entry.findall(f"{{{_ARXIV_NS}}}link"):
            if link.get("rel") == "alternate":
                arxiv_url = link.get("href", "")
                arxiv_id = arxiv_url.split("/abs/")[-1] if "/abs/" in arxiv_url else ""

        if not title or not abstract:
            continue

        papers.append(
            Paper(
                title=title,
                abstract=abstract[:1500],  # cap abstract length
                authors=authors[:5],
                date=published_str,
                source="arxiv",
                url=arxiv_url,
                arxiv_id=arxiv_id,
            )
        )

    return papers


# ─── Semantic Scholar ─────────────────────────────────────────────────────────

_SS_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_SS_FIELDS = "title,abstract,authors,year,publicationDate,citationCount,venue,url,externalIds"


def _search_semantic_scholar(query: str, max_results: int = 10) -> list[Paper]:
    """
    Query Semantic Scholar for recent papers.
    API docs: https://www.semanticscholar.org/product/api
    """
    since_year = (datetime.now(timezone.utc) - timedelta(days=30)).year
    since_date = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d")

    headers = {"Accept": "application/json"}
    if config.SEMANTIC_SCHOLAR_API_KEY:
        headers["x-api-key"] = config.SEMANTIC_SCHOLAR_API_KEY

    params = {
        "query": query,
        "limit": max_results,
        "fields": _SS_FIELDS,
        "publicationDateOrYear": f"{since_year}-",  # filter to last year minimum
    }

    resp = requests.get(_SS_SEARCH_URL, params=params, headers=headers, timeout=20)
    if resp.status_code == 429:
        # Rate limited — skip this source silently
        return []
    resp.raise_for_status()

    papers = []
    for item in resp.json().get("data", []):
        pub_date = item.get("publicationDate") or str(item.get("year", ""))
        if not pub_date:
            continue

        # Only keep papers from last 30 days
        try:
            if len(pub_date) == 10:  # YYYY-MM-DD
                if pub_date < since_date:
                    continue
            else:
                # Only year available — include if recent enough
                if int(pub_date) < since_year:
                    continue
        except (ValueError, TypeError):
            continue

        arxiv_id = (item.get("externalIds") or {}).get("ArXiv", None)
        url = item.get("url") or (
            f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""
        )

        papers.append(
            Paper(
                title=(item.get("title") or "").strip(),
                abstract=(item.get("abstract") or "").strip()[:1500],
                authors=[
                    a.get("name", "") for a in (item.get("authors") or [])[:5]
                ],
                date=pub_date[:10] if len(pub_date) >= 10 else pub_date,
                source="semantic_scholar",
                url=url,
                arxiv_id=arxiv_id,
                citation_count=item.get("citationCount"),
                venue=item.get("venue"),
            )
        )

    return papers


# ─── Deduplication ────────────────────────────────────────────────────────────

def _deduplicate(papers: list[Paper]) -> list[Paper]:
    """
    Remove duplicates by matching arXiv ID (if present) or normalised title.
    Prefer the arXiv entry over the Semantic Scholar one when both exist.
    """
    seen_arxiv: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[Paper] = []

    for p in papers:
        if p.arxiv_id and p.arxiv_id in seen_arxiv:
            continue
        norm_title = re.sub(r"\s+", " ", p.title.lower().strip())
        if norm_title in seen_titles:
            continue
        if p.arxiv_id:
            seen_arxiv.add(p.arxiv_id)
        seen_titles.add(norm_title)
        unique.append(p)

    return unique


# ─── Public interface ─────────────────────────────────────────────────────────

def retrieve_papers(keywords: list[str], papers_per_keyword: int = config.PAPERS_PER_TOPIC) -> list[Paper]:
    """
    For each keyword, search arXiv and Semantic Scholar.
    Returns deduplicated candidate papers.
    """
    all_papers: list[Paper] = []

    for kw in keywords:
        # arXiv
        try:
            arxiv_results = _search_arxiv(kw, max_results=papers_per_keyword)
            all_papers.extend(arxiv_results)
        except Exception as e:
            print(f"[retriever] arXiv search failed for '{kw}': {e}")

        # Small delay to be polite to arXiv
        time.sleep(0.5)

        # Semantic Scholar
        try:
            ss_results = _search_semantic_scholar(kw, max_results=papers_per_keyword)
            all_papers.extend(ss_results)
        except Exception as e:
            print(f"[retriever] Semantic Scholar search failed for '{kw}': {e}")

        time.sleep(0.3)

    return _deduplicate(all_papers)
