"""
competitive_intel/wiki.py
Writes structured pipeline outputs into the knowledge wiki.
"""

import os
import logging
from pathlib import Path
from datetime import datetime

from models import CompetitiveBrief, CompetitorFinding, PositioningComparison, ThreatOpportunity

WIKI_ROOT = Path(os.environ.get("WIKI_ROOT", "/data/wiki"))
logger = logging.getLogger("competitive_intel")


def slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    return text.lower().replace(" ", "-").replace("/", "-")[:60]


def write_finding(finding: CompetitorFinding, run_id: str, run_date: str):
    """Write a single competitor finding as a wiki page."""
    competitor_dir = WIKI_ROOT / "competitors" / slugify(finding.competitor)
    competitor_dir.mkdir(parents=True, exist_ok=True)

    slug = slugify(finding.summary[:50])
    filepath = competitor_dir / f"{run_date}-{slug}.md"

    specs_lines = "\n".join(f"- **{k}**: {v}" for k, v in finding.specs_mentioned.items())
    verticals = ", ".join(finding.target_verticals) if finding.target_verticals else "general"
    sources = "\n".join(f"- {url}" for url in finding.source_urls)

    content = f"""# {finding.summary[:80]}

**Summary**: {finding.summary}
**Competitor**: {finding.competitor}
**Category**: {finding.category}
**Verticals**: {verticals}
**Confidence**: {finding.confidence}
**Run**: {run_date} (run_id: {run_id})
**Created**: {run_date}
**Last Updated**: {run_date}

---

## Details

{finding.summary}

## Specs Mentioned

{specs_lines if specs_lines else "No specific specs mentioned."}

## Sources

{sources}
"""
    filepath.write_text(content)
    return filepath


def write_positioning(comparison: PositioningComparison, run_date: str):
    """Write or update a head-to-head positioning comparison."""
    positioning_dir = WIKI_ROOT / "positioning"
    positioning_dir.mkdir(parents=True, exist_ok=True)

    filepath = positioning_dir / f"vs-{slugify(comparison.competitor)}.md"

    content = f"""# HP vs {comparison.competitor}

**Last Updated**: {run_date}

---

## Their Narrative

{comparison.their_narrative}

## Where HP Wins

{comparison.hp_advantage}

## Where HP Has Gaps

{comparison.hp_gap}

## Recommended Response

{comparison.recommended_response}
"""
    filepath.write_text(content)
    return filepath


def write_threat_or_opportunity(item: ThreatOpportunity, run_id: str, run_date: str):
    """Write a threat or opportunity as a wiki page."""
    subdir = "threats" if item.type == "threat" else "opportunities"
    target_dir = WIKI_ROOT / subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    slug = slugify(item.description[:50])
    filepath = target_dir / f"{run_date}-{slug}.md"

    verticals = ", ".join(item.affected_verticals)

    content = f"""# {item.description[:80]}

**Type**: {item.type}
**Urgency**: {item.urgency}
**Affected Verticals**: {verticals}
**Run**: {run_date} (run_id: {run_id})
**Created**: {run_date}

---

## Details

{item.description}
"""
    filepath.write_text(content)
    return filepath


def write_weekly_brief(brief: dict):
    """Write the consolidated weekly brief from a dict."""
    briefs_dir = WIKI_ROOT / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)

    period = brief.get("period_covered", f"Week of {datetime.utcnow().strftime('%Y-%m-%d')}")
    run_id = brief.get("run_id", "unknown")
    generated = brief.get("generated_at", datetime.utcnow().isoformat())
    summary = brief.get("executive_summary", "No summary generated.")
    changes = brief.get("changes_since_last_run", "First run.")
    points = brief.get("talking_points", [])

    filepath = briefs_dir / f"{period.replace(' ', '-').lower()}.md"

    talking_points = "\n".join(f"- {tp}" for tp in points)

    content = f"""# Competitive Brief: {period}

**Run ID**: {run_id}
**Generated**: {generated}

---

## Executive Summary

{summary}

## Changes Since Last Run

{changes}

## Talking Points

{talking_points}
"""
    filepath.write_text(content)
    return filepath


def update_index():
    """Regenerate _index.md with a table of contents of all wiki pages."""
    index_lines = [
        "# Competitive Intelligence Wiki",
        "",
        f"**Last updated**: {datetime.utcnow().isoformat()}",
        "",
    ]

    for section in ["briefs", "competitors", "positioning", "threats", "opportunities"]:
        section_path = WIKI_ROOT / section
        if not section_path.exists():
            continue
        index_lines.append(f"## {section.title()}")
        index_lines.append("")
        for md_file in sorted(section_path.rglob("*.md")):
            if md_file.name.startswith("_"):
                continue
            rel_path = md_file.relative_to(WIKI_ROOT)
            first_line = md_file.read_text().split("\n")[0].lstrip("# ").strip()
            index_lines.append(f"- [{first_line}]({rel_path})")
        index_lines.append("")

    (WIKI_ROOT / "_index.md").write_text("\n".join(index_lines))


def publish_to_wiki_partial(analyst_output: dict):
    """
    Partial save when Strategist or Writer fails.
    Writes analyst findings to wiki without positioning or brief.
    """
    run_id = "partial"
    run_date = datetime.utcnow().strftime("%Y-%m-%d")
    files_written = []

    for finding_data in analyst_output["findings"]:
        finding = CompetitorFinding(**finding_data)
        try:
            f = write_finding(finding, run_id, run_date)
            files_written.append(str(f))
        except Exception as e:
            logger.warning(f"Failed to write finding to wiki: {e}")

    update_index()
    return files_written


def publish_to_wiki(brief: dict | None, analyst_output: dict, strategist_output: dict):
    """
    Main entry point. Called after the DAG completes.
    Writes all structured outputs into the wiki.
    brief can be None if the Writer failed (partial save).
    """
    run_id = brief["run_id"] if brief else "partial"
    run_date = str(brief["generated_at"])[:10] if brief else datetime.utcnow().strftime("%Y-%m-%d")

    files_written = []

    for finding_data in analyst_output["findings"]:
        finding = CompetitorFinding(**finding_data)
        try:
            f = write_finding(finding, run_id, run_date)
            files_written.append(str(f))
        except Exception as e:
            logger.warning(f"Failed to write finding to wiki: {e}")

    for comp_data in strategist_output["positioning_comparisons"]:
        comp = PositioningComparison(**comp_data)
        try:
            f = write_positioning(comp, run_date)
            files_written.append(str(f))
        except Exception as e:
            logger.warning(f"Failed to write positioning to wiki: {e}")

    for item_data in strategist_output["threats_and_opportunities"]:
        item = ThreatOpportunity(**item_data)
        try:
            f = write_threat_or_opportunity(item, run_id, run_date)
            files_written.append(str(f))
        except Exception as e:
            logger.warning(f"Failed to write threat/opportunity to wiki: {e}")

    if brief is not None:
        try:
            f = write_weekly_brief(brief)
            files_written.append(str(f))
        except Exception as e:
            logger.warning(f"Failed to write weekly brief to wiki: {e}")

    try:
        update_index()
    except Exception as e:
        logger.warning(f"Failed to update wiki index: {e}")

    return files_written
