#!/usr/bin/env python3
"""
extract_links.py
Extracts all source URLs from competitor findings, grouped by competitor.
Outputs full, untruncated links in a markdown file.

Run from the project root on the Nano:
    python3 extract_links.py

Output: data/competitor-source-links.md
"""

import os
import glob
from collections import defaultdict
from datetime import datetime

WIKI_ROOT = os.environ.get("WIKI_ROOT", "data/wiki")
OUTPUT_PATH = "data/competitor-source-links.md"


def extract_urls_from_file(filepath):
    """Extract all http/https URLs from a markdown finding file."""
    urls = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            # Source URLs appear as "- https://..." in the Sources section
            if line.startswith("- http"):
                url = line[2:].strip()
                # Remove any trailing markdown or punctuation
                url = url.rstrip(")")
                urls.append(url)
    return urls


def get_finding_summary(filepath):
    """Extract the Summary line from a finding file."""
    with open(filepath) as f:
        for line in f:
            if line.startswith("**Summary**:"):
                return line.replace("**Summary**:", "").strip()[:200]
    return os.path.basename(filepath)


def get_finding_date(filepath):
    """Extract date from filename (2026-05-21-...)."""
    basename = os.path.basename(filepath)
    parts = basename.split("-")
    if len(parts) >= 3:
        try:
            return f"{parts[0]}-{parts[1]}-{parts[2]}"
        except Exception:
            pass
    return "unknown"


def main():
    competitors_dir = os.path.join(WIKI_ROOT, "competitors")

    if not os.path.exists(competitors_dir):
        print(f"Error: {competitors_dir} not found. Run from the project root.")
        return

    # Collect all URLs by competitor
    all_data = {}

    for comp_dir in sorted(glob.glob(os.path.join(competitors_dir, "*"))):
        if not os.path.isdir(comp_dir):
            continue

        comp_name = os.path.basename(comp_dir)
        findings = sorted(glob.glob(os.path.join(comp_dir, "2026-*.md")))

        if not findings:
            continue

        comp_data = {
            "urls": defaultdict(list),  # url -> list of finding summaries that cite it
            "findings_count": len(findings),
        }

        for fpath in findings:
            urls = extract_urls_from_file(fpath)
            summary = get_finding_summary(fpath)
            date = get_finding_date(fpath)

            for url in urls:
                comp_data["urls"][url].append({
                    "summary": summary,
                    "date": date,
                })

        all_data[comp_name] = comp_data

    # Write markdown output
    lines = []
    lines.append("# Competitive Intelligence — Source Links by Competitor")
    lines.append("")
    lines.append(f"**Generated**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    total_urls = 0
    total_unique = 0

    for comp_name in sorted(all_data.keys()):
        comp = all_data[comp_name]
        unique_urls = len(comp["urls"])
        total_unique += unique_urls

        display_name = comp_name.replace("-", " ").title()
        lines.append(f"---")
        lines.append("")
        lines.append(f"## {display_name}")
        lines.append("")
        lines.append(f"**Findings**: {comp['findings_count']}  |  **Unique sources**: {unique_urls}")
        lines.append("")

        for url in sorted(comp["urls"].keys()):
            citations = comp["urls"][url]
            total_urls += 1
            lines.append(f"- {url}")
            for cite in citations[:2]:  # Show up to 2 citing findings per URL
                lines.append(f"  - [{cite['date']}] {cite['summary'][:120]}")
            if len(citations) > 2:
                lines.append(f"  - *(+{len(citations) - 2} more findings cite this source)*")

        lines.append("")

    # Summary at top
    summary_lines = [
        "",
        f"**Total competitors**: {len(all_data)}  |  **Total unique sources**: {total_unique}",
        "",
    ]
    lines[3:3] = summary_lines

    output = "\n".join(lines)

    with open(OUTPUT_PATH, "w") as f:
        f.write(output)

    print(f"Written to {OUTPUT_PATH}")
    print(f"  {len(all_data)} competitors, {total_unique} unique sources")


if __name__ == "__main__":
    main()