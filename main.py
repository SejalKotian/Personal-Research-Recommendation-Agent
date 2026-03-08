"""
Main orchestrator — run from the CLI:

    python main.py

Optional flags:
    --lookback 10          Days of OneNote history to read (default: from .env)
    --section-id <id>      Restrict to a specific OneNote section
    --notebook-id <id>     Restrict to a specific notebook
    --dry-run              Skip OneNote auth; use sample notes for testing
    --notes-file <path>    Read notes from a local .txt file instead of OneNote
    --output <file>        Save digest to a file (e.g. digest.txt or digest.md)
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

import config
from storage.db import init_db, get_seen_urls, save_recommended_papers, log_digest_run
from connectors.onenote import get_pages_text
from agents.context_summarizer import extract_research_profile
from agents.paper_retriever import retrieve_papers
from agents.ranker import rank_papers
from agents.presenter import format_terminal, format_markdown, format_dict
from notifications.email_sender import send_digest_email

console = Console()


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


def _load_notes_file(path: str) -> list[dict]:
    """Read a plain text file and return it as a single page dict."""
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return []
    return [{"id": "file-1", "title": Path(path).name, "created": "", "modified": "", "text": text}]


def run_pipeline(
    lookback_days: int,
    section_id: str | None,
    notebook_id: str | None,
    dry_run: bool,
    notes_file: str | None = None,
    output_path: str | None = None,
    send_email: bool = False,
) -> None:
    init_db()

    with Progress(SpinnerColumn(), TextColumn("{task.description}"), console=console) as progress:

        # ── Step 1: Fetch notes ──────────────────────────────────────────────
        task = progress.add_task("Loading notes...", total=None)
        if notes_file:
            pages = _load_notes_file(notes_file)
            console.print(f"[yellow]Using notes from file: {notes_file}[/yellow]")
        elif dry_run:
            pages = SAMPLE_NOTES
            console.print("[yellow]DRY RUN: using built-in sample notes[/yellow]")
        else:
            pages = get_pages_text(
                lookback_days=lookback_days,
                section_id=section_id,
                notebook_id=notebook_id,
            )
        progress.update(task, description=f"Loaded {len(pages)} note(s)", completed=True)

        if not pages:
            console.print(
                "[red]No notes found. Check your file path or try --dry-run.[/red]"
            )
            sys.exit(1)

        # ── Step 2: Extract research profile ────────────────────────────────
        task = progress.add_task("Extracting research profile with Claude...", total=None)
        profile = extract_research_profile(pages)
        progress.update(task, description="Research profile extracted", completed=True)

        console.print("\n[bold cyan]Your week's research profile:[/bold cyan]")
        for t in profile.active_topics:
            console.print(f"  * {t}")

        # ── Step 3: Retrieve candidate papers ───────────────────────────────
        # Use only the top 6 keywords to keep API calls manageable
        search_keywords = profile.keywords[:6]
        task = progress.add_task(
            f"Searching papers for {len(search_keywords)} keywords...", total=None
        )
        candidates = retrieve_papers(search_keywords, papers_per_keyword=config.PAPERS_PER_TOPIC)
        progress.update(
            task,
            description=f"Found {len(candidates)} unique candidate papers",
            completed=True,
        )

        if not candidates:
            console.print("[red]No papers found. Try different keywords or check your API access.[/red]")
            sys.exit(1)

        # ── Step 4: Rank ─────────────────────────────────────────────────────
        task = progress.add_task("Ranking and explaining papers with Claude...", total=None)
        seen_urls = get_seen_urls()
        ranked = rank_papers(
            profile,
            candidates,
            seen_paper_urls=seen_urls,
            top_n=config.TOP_N_PAPERS,
        )
        progress.update(task, description="Ranking complete", completed=True)

    # ── Step 5: Present ──────────────────────────────────────────────────────
    digest = format_terminal(profile, ranked)
    console.print(digest)

    if output_path:
        path = Path(output_path)
        if path.suffix == ".md":
            content = format_markdown(profile, ranked)
        else:
            content = format_terminal(profile, ranked)
        path.write_text(content, encoding="utf-8")
        console.print(f"[green]Digest saved to {path}[/green]")

    if send_email:
        date_str = datetime.now().strftime("%B %d, %Y")
        subject = f"Your Weekly Digest - {date_str} by Radar"
        md_content = format_markdown(profile, ranked)
        try:
            send_digest_email(subject=subject, markdown_body=md_content)
            console.print("[green]Digest emailed successfully![/green]")
        except Exception as e:
            console.print(f"[red]Email failed: {e}[/red]")

    # ── Step 6: Persist ──────────────────────────────────────────────────────
    digest_dict = format_dict(profile, ranked)
    log_digest_run(profile.model_dump(), digest_dict, lookback_days)
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Weekly Research Recommendation Agent")
    parser.add_argument(
        "--lookback",
        type=int,
        default=config.LOOKBACK_DAYS,
        help=f"Days of OneNote history to analyse (default: {config.LOOKBACK_DAYS})",
    )
    parser.add_argument("--section-id", default=None, help="OneNote section ID to restrict to")
    parser.add_argument("--notebook-id", default=None, help="OneNote notebook ID to restrict to")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use built-in sample notes instead of fetching from OneNote",
    )
    parser.add_argument(
        "--notes-file",
        default=None,
        help="Path to a plain text file containing your notes (no Microsoft auth needed)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Save digest to a file, e.g. digest.txt or digest.md",
    )
    parser.add_argument(
        "--email",
        action="store_true",
        help="Send the digest by email (requires EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENT env vars)",
    )

    args = parser.parse_args()

    run_pipeline(
        lookback_days=args.lookback,
        section_id=args.section_id,
        notebook_id=args.notebook_id,
        dry_run=args.dry_run,
        notes_file=args.notes_file,
        output_path=args.output,
        send_email=args.email,
    )


if __name__ == "__main__":
    main()
