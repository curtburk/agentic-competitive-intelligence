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


# Canonical competitor name mapping
# Maps model-produced variants to the config-defined name
COMPETITOR_ALIASES = {
    "dell technologies": "dell",
    "dell tech": "dell",
    "msi (via ant pc)": "msi",
    "msi-(via-ant-pc)": "msi",
    "msi via ant pc": "msi",
    "ant pc": "msi",
    "ant-pc": "msi",
    "hewlett packard enterprise": "hpe",
    "general-market-competitors": "general-market",
    "general market competitors": "general-market",
}


def normalize_competitor(name: str) -> str:
    """Normalize competitor name to canonical form."""
    lower = name.lower().strip()
    if lower in COMPETITOR_ALIASES:
        return COMPETITOR_ALIASES[lower]
    return lower


def find_existing_urls(competitor_dir: Path) -> set:
    """Scan existing findings for source URLs to detect duplicates."""
    urls = set()
    for f in competitor_dir.glob("2026-*.md"):
        try:
            text = f.read_text()
            for line in text.split("\n"):
                line = line.strip()
                if line.startswith("- http"):
                    urls.add(line[2:].strip())
        except Exception:
            pass
    return urls

def write_finding(finding: CompetitorFinding, run_id: str, run_date: str):
    """Write a single competitor finding as a wiki page."""
    canonical = normalize_competitor(finding.competitor)
    competitor_dir = WIKI_ROOT / "competitors" / slugify(canonical)
    competitor_dir.mkdir(parents=True, exist_ok=True)

    # Dedup: skip if ALL source URLs already exist in prior findings
    if finding.source_urls:
        existing_urls = find_existing_urls(competitor_dir)
        new_urls = [u for u in finding.source_urls if u not in existing_urls]
        if not new_urls:
            return None

    slug = slugify(finding.summary[:50])
    filepath = competitor_dir / f"{run_date}-{slug}.md"

    if filepath.exists():
        return None
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

    file_content = f"""# Competitive Brief: {period}

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
    filepath.write_text(file_content)
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
    run_date = str(brief.get("generated_at", datetime.utcnow().isoformat()))[:10] if brief else datetime.utcnow().strftime("%Y-%m-%d")

    files_written = []

    for finding_data in analyst_output["findings"]:
        finding = CompetitorFinding(**finding_data)
        try:
            f = write_finding(finding, run_id, run_date)
            files_written.append(str(f))
        except Exception as e:
            logger.warning(f"Failed to write finding to wiki: {e}")

        try:
            from provenance import build_provenance_from_finding
            build_provenance_from_finding(
                competitor=finding.competitor,
                product_name=finding.competitor,
                finding_data=finding_data,
            )
        except Exception as e:
            logger.warning(f"Failed to track provenance for finding: {e}")

    # Write competitor strategy assessments
    strategies = strategist_output.get("competitor_strategies", {})
    if strategies:
        strategy_dir = WIKI_ROOT / "positioning"
        strategy_dir.mkdir(parents=True, exist_ok=True)
        for competitor, assessment in strategies.items():
            slug = competitor.lower().replace(" ", "-").replace("/", "-")[:40]
            filepath = strategy_dir / f"strategy-{slug}.md"

            # Read existing strategy to include as "previous assessment"
            previous = ""
            if filepath.exists():
                previous = filepath.read_text()

            file_content = f"# {competitor} — Inferred AI Strategy\n\n"
            file_content += f"**Last Updated**: {run_date}\n"
            file_content += f"**Run ID**: {run_id}\n\n---\n\n"
            file_content += f"## Current Assessment\n\n{assessment}\n"

            if previous and "## Current Assessment" in previous:
                old_assessment = previous.split("## Current Assessment")[1].split("## Previous Assessment")[0].strip()
                file_content += f"\n## Previous Assessment\n\n{old_assessment}\n"

            filepath.write_text(file_content)
            files_written.append(str(filepath))

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
            # brief passed directly as dict
            f = write_weekly_brief(brief)
            files_written.append(str(f))
        except Exception as e:
            logger.warning(f"Failed to write weekly brief to wiki: {e}")

    try:
        update_index()
    except Exception as e:
        logger.warning(f"Failed to update wiki index: {e}")

    return files_written
