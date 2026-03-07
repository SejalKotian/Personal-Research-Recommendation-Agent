"""
OneNote connector via Microsoft Graph.

Fetches pages from the last N days across all notebooks (or a specific section)
and returns their plain-text content.

Microsoft Graph OneNote API reference:
  https://learn.microsoft.com/en-us/graph/api/resources/onenote-api-overview
"""

import re
import html
from datetime import datetime, timedelta, timezone
from typing import Optional
import requests

import config
from auth.graph_auth import get_access_token


def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _strip_html(raw_html: str) -> str:
    """Very lightweight HTML-to-text: strips tags and decodes entities."""
    text = re.sub(r"<style[^>]*>.*?</style>", "", raw_html, flags=re.DOTALL)
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def list_notebooks(token: str) -> list[dict]:
    """Return all OneNote notebooks for the signed-in user."""
    url = f"{config.GRAPH_BASE_URL}/me/onenote/notebooks"
    resp = requests.get(url, headers=_headers(token))
    resp.raise_for_status()
    return resp.json().get("value", [])


def list_sections(token: str, notebook_id: Optional[str] = None) -> list[dict]:
    """Return sections — all sections across notebooks, or within one notebook."""
    if notebook_id:
        url = f"{config.GRAPH_BASE_URL}/me/onenote/notebooks/{notebook_id}/sections"
    else:
        url = f"{config.GRAPH_BASE_URL}/me/onenote/sections"
    resp = requests.get(url, headers=_headers(token))
    resp.raise_for_status()
    return resp.json().get("value", [])


def fetch_recent_pages(
    token: str,
    lookback_days: int = config.LOOKBACK_DAYS,
    section_id: Optional[str] = None,
    notebook_id: Optional[str] = None,
) -> list[dict]:
    """
    Return pages created or modified in the last `lookback_days` days.

    Each item:
        {
            "id": str,
            "title": str,
            "created": str (ISO 8601),
            "modified": str (ISO 8601),
            "text": str,   # extracted plain text
        }

    Pass `section_id` or `notebook_id` to narrow the search.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    if section_id:
        base = f"{config.GRAPH_BASE_URL}/me/onenote/sections/{section_id}/pages"
    elif notebook_id:
        base = f"{config.GRAPH_BASE_URL}/me/onenote/notebooks/{notebook_id}/pages"
    else:
        base = f"{config.GRAPH_BASE_URL}/me/onenote/pages"

    # Graph OData filter on lastModifiedDateTime
    url = (
        f"{base}"
        f"?$filter=lastModifiedDateTime ge {cutoff_str}"
        f"&$select=id,title,createdDateTime,lastModifiedDateTime"
        f"&$orderby=lastModifiedDateTime desc"
        f"&$top=50"
    )

    resp = requests.get(url, headers=_headers(token))
    resp.raise_for_status()
    pages_meta = resp.json().get("value", [])

    results = []
    for page in pages_meta:
        page_id = page["id"]
        content_url = f"{config.GRAPH_BASE_URL}/me/onenote/pages/{page_id}/content"
        content_resp = requests.get(content_url, headers=_headers(token))

        if content_resp.status_code != 200:
            # Skip pages where content fetch fails (e.g. permissions)
            continue

        raw_html = content_resp.text
        plain_text = _strip_html(raw_html)

        results.append(
            {
                "id": page_id,
                "title": page.get("title", "(untitled)"),
                "created": page.get("createdDateTime", ""),
                "modified": page.get("lastModifiedDateTime", ""),
                "text": plain_text,
            }
        )

    return results


def get_pages_text(
    lookback_days: int = config.LOOKBACK_DAYS,
    section_id: Optional[str] = None,
    notebook_id: Optional[str] = None,
) -> list[dict]:
    """
    Top-level convenience function: authenticate, fetch, return page dicts.
    Call this from orchestration code.
    """
    token = get_access_token()
    pages = fetch_recent_pages(
        token,
        lookback_days=lookback_days,
        section_id=section_id,
        notebook_id=notebook_id,
    )
    return pages
