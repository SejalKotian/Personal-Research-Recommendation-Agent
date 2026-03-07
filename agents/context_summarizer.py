"""
Context Summarizer Agent

Takes raw OneNote page text from the last N days and uses Claude to produce
a structured research profile:
  - active_topics
  - current_tasks
  - keywords (for paper search)
  - negative_filters (topics to deprioritize)
  - context_summary (short human-readable summary)
"""

import json
import re
from typing import Optional
import anthropic
from pydantic import BaseModel

import config


class ResearchProfile(BaseModel):
    active_topics: list[str]
    current_tasks: list[str]
    keywords: list[str]
    negative_filters: list[str]
    context_summary: str


_SYSTEM_PROMPT = """\
You are an assistant that reads a researcher's personal notes and extracts a \
structured research profile to help find relevant recent academic papers.

Your job is to identify:
1. active_topics — the main research/study/project themes active this week
   (be specific, e.g. "graph neural networks for materials discovery" not just "ML")
2. current_tasks — concrete things the user is working on right now
3. keywords — 8-15 search keywords/phrases for querying academic databases,
   covering the topics from different angles
4. negative_filters — topics explicitly mentioned as unrelated, boring, or to skip
5. context_summary — 2-3 sentences summarizing the user's week for a human reader

Output ONLY valid JSON matching this exact schema, no markdown fences:
{
  "active_topics": [...],
  "current_tasks": [...],
  "keywords": [...],
  "negative_filters": [...],
  "context_summary": "..."
}
"""


def _build_notes_block(pages: list[dict], max_chars: int = 12000) -> str:
    """
    Concatenate page texts into a single string, newest first, up to max_chars.
    Strips very short pages (likely blank/boilerplate).
    """
    chunks = []
    total = 0
    for page in pages:
        title = page.get("title", "(untitled)")
        text = page.get("text", "").strip()
        if len(text) < 30:
            continue
        date = page.get("modified", page.get("created", ""))[:10]
        chunk = f"--- [{date}] {title} ---\n{text}"
        if total + len(chunk) > max_chars:
            # Truncate the last chunk to fit
            remaining = max_chars - total
            chunk = chunk[:remaining] + "\n[... truncated ...]"
            chunks.append(chunk)
            break
        chunks.append(chunk)
        total += len(chunk)
    return "\n\n".join(chunks)


def extract_research_profile(pages: list[dict]) -> ResearchProfile:
    """
    Given a list of OneNote page dicts (from the connector), call Claude
    and return a structured ResearchProfile.
    """
    if not pages:
        return ResearchProfile(
            active_topics=[],
            current_tasks=[],
            keywords=[],
            negative_filters=[],
            context_summary="No notes found for the selected time period.",
        )

    notes_block = _build_notes_block(pages)

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    message = client.messages.create(
        model=config.CLAUDE_MODEL,
        max_tokens=1024,
        system=_SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Here are my notes from the last {config.LOOKBACK_DAYS} days.\n\n"
                    f"{notes_block}\n\n"
                    "Extract my research profile as JSON."
                ),
            }
        ],
    )

    raw = message.content[0].text.strip()

    # Strip markdown code fences if the model adds them anyway
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)

    data = json.loads(raw)
    return ResearchProfile(**data)
