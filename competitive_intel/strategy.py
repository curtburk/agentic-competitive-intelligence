"""
competitive_intel/strategy.py
Standalone strategy inference for individual competitors.
Completely independent from the pipeline DAG.

Loads all wiki data for a competitor, makes one focused LLM call,
writes the strategy assessment to the wiki.

Usage via API: POST /strategy {"competitor": "Dell"}
Usage via TUI: Strategy tab, type competitor name, click Assess
"""

import json
import os
import glob
import logging
import httpx
from datetime import datetime
from pathlib import Path

WIKI_ROOT = Path(os.environ.get("WIKI_ROOT", "/data/wiki"))
VLLM_URL = os.environ.get("VLLM_URL", "http://vllm:8000")
VLLM_MODEL = os.environ.get("VLLM_MODEL", "Qwen/Qwen3.6-35B-A3B")

logger = logging.getLogger("competitive_intel")


STRATEGY_PROMPT = """You are a competitive intelligence strategist analyzing a single competitor
for HP's AI workstation business (ZGX Nano and ZGX Fury product lines).

You will receive ALL available intelligence about this competitor:
- Their product profile (specs, pricing, positioning language)
- All findings from automated monitoring (product launches, partnerships, pricing moves, customer wins)
- Their previous strategy assessment (if one exists)
- HP's own product specs for comparison context

Produce a strategy assessment in 3-4 paragraphs covering:

1. STRATEGIC DIRECTION: What is this competitor building toward? Are they a platform play,
   price leader, vertical specialist, ecosystem builder? What pattern do their recent
   moves reveal about their long-term intentions?

2. NARRATIVE EVOLUTION: How has their messaging and positioning changed? Are they
   doubling down on hardware specs, pivoting to software/services, pushing cost narratives,
   or targeting specific verticals? If you have a previous assessment, explicitly state
   what has changed.

3. COMPETITIVE IMPLICATIONS FOR HP: Where does this competitor's strategy create risk
   for HP ZGX? Where does it create opportunity? Be specific about which HP product
   (Nano or Fury) is most affected and what HP should do about it.

4. RECOMMENDED COUNTER-POSITIONING: Give 2-3 specific talking points a salesperson
   could use when this competitor comes up in a customer conversation. These must be
   grounded in the data provided, not generic.

CRITICAL:
- Base your assessment ONLY on the data provided. Do not invent findings.
- If data is thin, say so. A short honest assessment beats a long fabricated one.
- Reference specific findings by date when possible.
- Do NOT produce JSON. Respond with plain text paragraphs only."""


def _load_competitor_context(competitor: str) -> dict:
    """Load all wiki data for a single competitor."""
    context = {}
    slug = competitor.lower().replace(" ", "-").replace("/", "-")

    # Try exact match first, then fuzzy
    comp_dir = WIKI_ROOT / "competitors" / slug
    if not comp_dir.exists():
        # Try to find a matching directory
        for d in (WIKI_ROOT / "competitors").iterdir():
            if d.is_dir() and slug in d.name:
                comp_dir = d
                break

    if not comp_dir.exists():
        return {"error": f"No wiki directory found for '{competitor}'. Tried: {slug}"}

    # Load profile
    profile = comp_dir / "profile.md"
    if profile.exists():
        context["profile"] = profile.read_text()

    # Load ALL findings (not capped)
    findings = sorted(comp_dir.glob("2026-*.md"))
    if findings:
        context["findings"] = []
        for f in findings:
            context["findings"].append({
                "filename": f.name,
                "content": f.read_text()
            })
        context["findings_count"] = len(findings)

    # Load previous strategy assessment
    strategy_file = WIKI_ROOT / "positioning" / f"strategy-{slug}.md"
    if not strategy_file.exists():
        # Try fuzzy match
        for sf in (WIKI_ROOT / "positioning").glob("strategy-*.md"):
            if slug in sf.name:
                strategy_file = sf
                break

    if strategy_file.exists():
        context["previous_strategy"] = strategy_file.read_text()

    # Load positioning comparison
    vs_file = WIKI_ROOT / "positioning" / f"vs-{slug}.md"
    if not vs_file.exists():
        for vf in (WIKI_ROOT / "positioning").glob("vs-*.md"):
            if slug in vf.name:
                vs_file = vf
                break

    if vs_file.exists():
        context["positioning_comparison"] = vs_file.read_text()

    # Load provenance data
    for prov_file in comp_dir.glob("provenance-*.json"):
        try:
            context["provenance"] = json.loads(prov_file.read_text())
        except Exception:
            pass

    return context


def _load_hp_context() -> dict:
    """Load HP product specs for comparison."""
    hp = {}
    for spec_name in ["zgx-fury-specs.md", "zgx-nano-specs.md", "compliance-by-architecture.md"]:
        spec_path = WIKI_ROOT / "positioning" / spec_name
        if spec_path.exists():
            hp[spec_name] = spec_path.read_text()
    return hp


def _write_strategy(competitor: str, assessment: str) -> str:
    """Write strategy assessment to wiki, preserving previous assessment."""
    strategy_dir = WIKI_ROOT / "positioning"
    strategy_dir.mkdir(parents=True, exist_ok=True)

    slug = competitor.lower().replace(" ", "-").replace("/", "-")[:40]
    filepath = strategy_dir / f"strategy-{slug}.md"

    # Read existing to preserve as previous
    previous_section = ""
    if filepath.exists():
        existing = filepath.read_text()
        if "## Current Assessment" in existing:
            old_assessment = existing.split("## Current Assessment")[1]
            if "## Previous Assessment" in old_assessment:
                old_assessment = old_assessment.split("## Previous Assessment")[0]
            previous_section = f"\n## Previous Assessment\n\n{old_assessment.strip()}\n"

    content = f"""# {competitor} — Inferred AI Strategy

**Last Updated**: {datetime.utcnow().strftime('%Y-%m-%d')}

---

## Current Assessment

{assessment}
{previous_section}"""

    filepath.write_text(content)
    return str(filepath)


async def assess_competitor(competitor: str) -> dict:
    """
    Run a standalone strategy assessment for one competitor.
    Returns the assessment text and metadata.
    """
    result = {
        "competitor": competitor,
        "status": "complete",
    }

    # Load all context
    comp_context = _load_competitor_context(competitor)
    if "error" in comp_context:
        result["status"] = "failed"
        result["reason"] = comp_context["error"]
        return result

    hp_context = _load_hp_context()

    # Build the user message
    sections = []

    if "profile" in comp_context:
        sections.append(f"=== COMPETITOR PROFILE ===\n{comp_context['profile']}")

    if "findings" in comp_context:
        sections.append(f"=== FINDINGS ({comp_context['findings_count']} total) ===")
        for f in comp_context["findings"]:
            sections.append(f"--- {f['filename']} ---\n{f['content'][:600]}")

    if "previous_strategy" in comp_context:
        sections.append(f"=== PREVIOUS STRATEGY ASSESSMENT ===\n{comp_context['previous_strategy']}")

    if "positioning_comparison" in comp_context:
        sections.append(f"=== HP POSITIONING vs {competitor.upper()} ===\n{comp_context['positioning_comparison']}")

    sections.append("=== HP PRODUCT CONTEXT ===")
    for name, content in hp_context.items():
        sections.append(f"--- {name} ---\n{content[:800]}")

    user_message = f"Assess the AI strategy of: {competitor}\n\n" + "\n\n".join(sections)

    # Sanitize control characters
    user_message = user_message.replace("\r", " ").replace("\x00", "")

    result["context_size"] = len(user_message)
    result["findings_count"] = comp_context.get("findings_count", 0)

    # Make the LLM call
    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                f"{VLLM_URL}/v1/chat/completions",
                json={
                    "model": VLLM_MODEL,
                    "messages": [
                        {"role": "system", "content": STRATEGY_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    "temperature": 0.3,
                    "max_tokens": 4096,
                },
            )
            resp.raise_for_status()
            response = resp.json()

            assessment = response["choices"][0]["message"]["content"]
            usage = response.get("usage", {})

            result["input_tokens"] = usage.get("prompt_tokens", 0)
            result["output_tokens"] = usage.get("completion_tokens", 0)

    except Exception as e:
        result["status"] = "failed"
        result["reason"] = f"LLM call failed: {str(e)[:200]}"
        logger.error(f"[strategy] Failed for {competitor}: {e}")
        return result

    # Write to wiki
    filepath = _write_strategy(competitor, assessment)
    result["wiki_path"] = filepath
    result["assessment"] = assessment

    logger.info(
        f"[strategy] {competitor}: {result['findings_count']} findings, "
        f"{result.get('input_tokens', 0)} in / {result.get('output_tokens', 0)} out tokens"
    )

    return result


async def assess_all_competitors() -> dict:
    """Run strategy assessment for every competitor with a wiki directory."""
    comp_dir = WIKI_ROOT / "competitors"
    if not comp_dir.exists():
        return {"status": "failed", "reason": "No competitors directory"}

    results = {}
    for d in sorted(comp_dir.iterdir()):
        if d.is_dir() and not d.name.startswith("."):
            name = d.name.replace("-", " ").title()
            result = await assess_competitor(d.name)
            results[d.name] = {
                "status": result["status"],
                "findings_count": result.get("findings_count", 0),
                "output_tokens": result.get("output_tokens", 0),
            }

    return {"status": "complete", "competitors": results}