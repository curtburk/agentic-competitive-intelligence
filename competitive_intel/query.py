"""
competitive_intel/query.py
Natural language query interface over the knowledge wiki.
Includes provenance data so the model can answer "where did this come from?"
"""

import json
import os
from datetime import datetime
from pathlib import Path

WIKI_ROOT = Path(os.environ.get("WIKI_ROOT", "/data/wiki"))


def scan_wiki(query: str, max_files: int = 15) -> list[dict]:
    """
    Scan wiki files for relevance to a query.
    Uses metadata keyword matching and recency weighting.
    Returns a ranked list of {path, title, summary, content, score}.
    Also includes relevant provenance JSON files.
    """
    query_terms = set(query.lower().split())
    candidates = []

    if not WIKI_ROOT.exists():
        return []

    # Scan markdown files
    for md_file in WIKI_ROOT.rglob("*.md"):
        if md_file.name.startswith("_"):
            continue

        text = md_file.read_text()
        lines = text.split("\n")

        title = lines[0].lstrip("# ").strip() if lines else md_file.stem
        summary = ""
        competitor = ""
        category = ""
        created = ""

        for line in lines[:15]:
            if line.startswith("**Summary**:"):
                summary = line.split(":", 1)[1].strip()
            elif line.startswith("**Competitor**:"):
                competitor = line.split(":", 1)[1].strip().lower()
            elif line.startswith("**Category**:"):
                category = line.split(":", 1)[1].strip().lower()
            elif line.startswith("**Created**:"):
                created = line.split(":", 1)[1].strip()

        searchable = f"{title} {summary} {competitor} {category}".lower()
        term_hits = sum(1 for term in query_terms if term in searchable)

        if term_hits == 0:
            continue

        recency_bonus = 0
        if created:
            try:
                age_days = (datetime.utcnow() - datetime.fromisoformat(created)).days
                recency_bonus = max(0, 10 - age_days) * 0.1
            except ValueError:
                pass

        score = term_hits + recency_bonus

        candidates.append({
            "path": str(md_file.relative_to(WIKI_ROOT)),
            "title": title,
            "summary": summary,
            "content": text,
            "score": score,
        })

    # Scan provenance JSON files
    for json_file in WIKI_ROOT.rglob("provenance-*.json"):
        try:
            data = json.loads(json_file.read_text())
            competitor = data.get("competitor", "").lower()
            product = data.get("product_name", "").lower()
            searchable = f"{competitor} {product} provenance source"

            # Also search through claim keys and values
            claims = data.get("claims", {})
            for key, claim_list in claims.items():
                searchable += f" {key}"
                for claim in claim_list:
                    searchable += f" {claim.get('value', '')}"

            searchable = searchable.lower()
            term_hits = sum(1 for term in query_terms if term in searchable)

            # Boost provenance files when query asks about sources
            source_terms = {"source", "where", "from", "url", "provenance", "cite", "citation", "proof", "evidence"}
            if query_terms & source_terms:
                term_hits += 2  # boost when asking about sources

            if term_hits == 0:
                continue

            # Format provenance as readable text
            prov_text = _format_provenance_json(data)

            candidates.append({
                "path": str(json_file.relative_to(WIKI_ROOT)),
                "title": f"Provenance: {data.get('competitor', '')} {data.get('product_name', '')}",
                "summary": f"Source tracking for {data.get('product_name', '')} claims",
                "content": prov_text,
                "score": term_hits,
            })
        except Exception:
            continue

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates[:max_files]


def _format_provenance_json(data: dict) -> str:
    """Format a provenance JSON record as readable text for the LLM."""
    lines = [
        f"# Provenance: {data.get('competitor', '')} {data.get('product_name', '')}",
        f"Last updated: {data.get('last_updated', '')}",
        "",
    ]

    claims = data.get("claims", {})
    for claim_key, claim_list in claims.items():
        if claim_key.startswith("_"):
            continue
        lines.append(f"## {claim_key}")
        for c in claim_list:
            lines.append(f"- Value: {c.get('value', '')}")
            lines.append(f"  Source URL: {c.get('source_url', '')}")
            lines.append(f"  Extracted: {c.get('extracted_date', '')}")
            if c.get("context"):
                lines.append(f"  Context: {c['context']}")
        lines.append("")

    return "\n".join(lines)


def build_query_prompt(question: str, wiki_pages: list[dict]) -> str:
    """
    Build a prompt that includes relevant wiki context and the user's question.
    """
    context_blocks = []
    for page in wiki_pages:
        context_blocks.append(
            f"--- FILE: {page['path']} ---\n{page['content']}\n"
        )

    context = "\n".join(context_blocks)

    return f"""You are a competitive intelligence analyst for HP's AI workstation business.
You have access to a knowledge wiki containing competitive findings, positioning
comparisons, threats, and opportunities gathered from automated monitoring.

You also have access to PROVENANCE files (provenance-*.json) that track where
each claim came from. When a user asks about the source of a specific fact,
price, or spec, check the provenance files for the exact URL and date.

Answer the user's question using ONLY the wiki content provided below.
When citing facts, include the source URL from the provenance data if available.
If the wiki doesn't contain enough information to answer, say so and suggest
what additional monitoring might help.

=== WIKI CONTEXT ===
{context}
=== END WIKI CONTEXT ===

Question: {question}"""
