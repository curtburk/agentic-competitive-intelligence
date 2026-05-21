#!/usr/bin/env python3
"""Export all wiki content into a single markdown file for review or slide building."""

from pathlib import Path
from datetime import datetime

WIKI_ROOT = Path("data/wiki")
OUTPUT_DIR = Path("data")

def export():
    timestamp = datetime.now().strftime("%Y-%m-%d")
    output_path = OUTPUT_DIR / f"all_data_{timestamp}.md"
    
    sections = []
    
    # Latest briefs
    briefs_dir = WIKI_ROOT / "briefs"
    if briefs_dir.exists():
        brief_files = sorted(briefs_dir.glob("*.md"), reverse=True)
        if brief_files:
            sections.append("# LATEST BRIEF\n")
            sections.append(brief_files[0].read_text())
            sections.append("\n---\n")
    
    # HP product specs
    sections.append("# HP PRODUCT SPECS\n")
    for name in ["compliance-by-architecture.md", "zgx-fury-specs.md", "zgx-nano-specs.md"]:
        path = WIKI_ROOT / "positioning" / name
        if path.exists():
            sections.append(f"## {name}\n")
            sections.append(path.read_text())
            sections.append("\n---\n")
    
    # Positioning comparisons
    sections.append("# POSITIONING COMPARISONS\n")
    pos_dir = WIKI_ROOT / "positioning"
    if pos_dir.exists():
        for f in sorted(pos_dir.glob("vs-*.md")):
            sections.append(f"## {f.name}\n")
            sections.append(f.read_text())
            sections.append("\n---\n")
    
    # Competitor profiles
    sections.append("# COMPETITOR PROFILES\n")
    comp_dir = WIKI_ROOT / "competitors"
    if comp_dir.exists():
        for competitor_dir in sorted(comp_dir.iterdir()):
            if not competitor_dir.is_dir():
                continue
            profile = competitor_dir / "profile.md"
            if profile.exists():
                sections.append(f"## {competitor_dir.name}/profile.md\n")
                sections.append(profile.read_text())
                sections.append("\n---\n")
    
    # Competitor findings
    sections.append("# COMPETITOR FINDINGS\n")
    if comp_dir.exists():
        for competitor_dir in sorted(comp_dir.iterdir()):
            if not competitor_dir.is_dir():
                continue
            findings = sorted(competitor_dir.glob("2026-*.md"))
            if findings:
                sections.append(f"## {competitor_dir.name}\n")
                for f in findings:
                    sections.append(f"### {f.name}\n")
                    sections.append(f.read_text())
                    sections.append("\n---\n")
    
    # Provenance
    sections.append("# PROVENANCE\n")
    if comp_dir.exists():
        for f in sorted(comp_dir.rglob("provenance-*.json")):
            rel = f.relative_to(WIKI_ROOT)
            sections.append(f"## {rel}\n")
            sections.append(f"```json\n{f.read_text()}\n```\n")
            sections.append("\n---\n")
    
    # Threats
    sections.append("# THREATS\n")
    threats_dir = WIKI_ROOT / "threats"
    if threats_dir.exists():
        for f in sorted(threats_dir.glob("*.md")):
            sections.append(f"## {f.name}\n")
            sections.append(f.read_text())
            sections.append("\n---\n")
    
    # Opportunities
    sections.append("# OPPORTUNITIES\n")
    opps_dir = WIKI_ROOT / "opportunities"
    if opps_dir.exists():
        for f in sorted(opps_dir.glob("*.md")):
            sections.append(f"## {f.name}\n")
            sections.append(f.read_text())
            sections.append("\n---\n")
    
    output = "\n".join(sections)
    output_path.write_text(output)
    print(f"Exported to {output_path} ({len(output):,} chars)")

if __name__ == "__main__":
    export()
