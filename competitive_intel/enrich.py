"""
competitive_intel/enrich.py
Product profile enrichment: search -> fetch -> extract -> write to wiki.
Skips the full DAG and directly enriches a competitor product profile.
"""

import httpx
import json
import os
import logging
import trafilatura
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel, Field

WIKI_ROOT = Path(os.environ.get("WIKI_ROOT", "/data/wiki"))
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://searxng:8080")
VLLM_URL = os.environ.get("VLLM_URL", "http://vllm:8000")
VLLM_MODEL = os.environ.get("VLLM_MODEL", "Qwen/Qwen3.6-35B-A3B")

logger = logging.getLogger("competitive_intel")


# ─────────────────────────────────────────────
# Pydantic model for enriched profile
# ─────────────────────────────────────────────

class EnrichedProfile(BaseModel):
    """Structured product profile extracted from web sources."""
    competitor: str
    product_name: str
    product_tier: str = Field(
        description="'fury' or 'nano' - which HP ZGX product this competes with"
    )
    overview: str = Field(
        description="2-3 sentence overview of the product and its market position"
    )
    specs: dict[str, str] = Field(
        description="Key specs: GPU, CPU, memory, TOPS, cooling, form factor, etc."
    )
    pricing: str = Field(
        description="Price or price range if found"
    )
    availability: str = Field(
        description="Available now, preorder, announced, etc."
    )
    target_verticals: list[str] = Field(
        description="Which verticals this product targets"
    )
    positioning_language: str = Field(
        description="How the competitor describes this product (their words, not ours)"
    )
    hp_comparison_notes: str = Field(
        description="How this compares to the relevant HP ZGX product"
    )
    sources: list[str] = Field(
        description="URLs used to build this profile"
    )


# ─────────────────────────────────────────────
# Agent prompt
# ─────────────────────────────────────────────

def enricher_prompt() -> str:
    return """You are a competitive intelligence analyst for HP's AI workstation business.

You will receive web page content about a specific competitor product. Your job is to
extract a structured product profile with as much detail as possible.

Extract:
- An overview of the product (what it is, who it's for)
- Technical specs (GPU, CPU, memory/VRAM, TOPS, cooling type, form factor, weight, etc.)
- Pricing (exact price or range, if mentioned)
- Availability (shipping now, preorder, announced, etc.)
- Target verticals (defense, healthcare, manufacturing, etc.)
- The competitor's own positioning language (how THEY describe the product)
- How this compares to the HP ZGX product it competes with

IMPORTANT:
- Only extract facts that are explicitly stated in the source material.
- Do not guess specs that aren't mentioned. Use "Not specified" for missing specs.
- For pricing, capture the exact figure if available, otherwise "Unknown."
- For positioning_language, use the competitor's actual marketing phrases.
- Be specific about GPU model, memory type (unified vs discrete VRAM), and cooling.

Respond with structured JSON matching the required schema."""


# ─────────────────────────────────────────────
# Search and fetch helpers
# ─────────────────────────────────────────────

async def search_for_product(
    competitor: str,
    product_name: str,
    url: str | None = None,
) -> list[dict]:
    """
    Search for a specific product and fetch full text from results.
    If a direct URL is provided, fetch that too.
    """
    sources = []

    # Fetch direct URL if provided
    if url:
        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                text = trafilatura.extract(
                    downloaded,
                    include_comments=False,
                    include_tables=True,
                    favor_recall=True,
                )
                if text and len(text.strip()) > 50:
                    sources.append({
                        "url": url,
                        "text": text.strip(),
                        "source": "direct_url",
                    })
        except Exception as e:
            logger.warning(f"Failed to fetch direct URL {url}: {e}")

    # Search for the product
    queries = [
        f"{competitor} {product_name}",
        f"{competitor} {product_name} specs pricing",
        f"{competitor} {product_name} review",
    ]

    for query in queries:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{SEARXNG_URL}/search",
                    params={"q": query, "format": "json", "categories": "general,news,it"}
                )
                resp.raise_for_status()
                results = resp.json().get("results", [])

                for result in results[:3]:
                    result_url = result.get("url", "")
                    # Skip if we already have this URL
                    if any(s["url"] == result_url for s in sources):
                        continue
                    try:
                        downloaded = trafilatura.fetch_url(result_url)
                        if downloaded:
                            text = trafilatura.extract(
                                downloaded,
                                include_comments=False,
                                include_tables=True,
                                favor_recall=True,
                            )
                            if text and len(text.strip()) > 100:
                                sources.append({
                                    "url": result_url,
                                    "text": text.strip()[:3000],  # cap to avoid context overflow
                                    "source": query,
                                })
                    except Exception:
                        continue
        except Exception as e:
            logger.warning(f"Search failed for '{query}': {e}")

    return sources


# ─────────────────────────────────────────────
# LLM extraction
# ─────────────────────────────────────────────

async def extract_profile(
    competitor: str,
    product_name: str,
    product_tier: str,
    sources: list[dict],
) -> EnrichedProfile | None:
    """Call the LLM to extract a structured profile from fetched sources."""

    source_text = "\n\n---\n\n".join(
        f"SOURCE: {s['url']}\n{s['text']}" for s in sources
    )

    user_content = json.dumps({
        "competitor": competitor,
        "product_name": product_name,
        "product_tier": product_tier,
        "hp_competitor": "ZGX Fury" if product_tier == "fury" else "ZGX Nano",
        "source_material": source_text,
        "source_urls": [s["url"] for s in sources],
    })

    schema = EnrichedProfile.model_json_schema()

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{VLLM_URL}/v1/chat/completions",
                json={
                    "model": VLLM_MODEL,
                    "messages": [
                        {"role": "system", "content": enricher_prompt()},
                        {"role": "user", "content": user_content},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 4096,
                    "response_format": {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "EnrichedProfile",
                            "schema": schema,
                        },
                    },
                },
            )
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            parsed = json.loads(raw)
            return EnrichedProfile(**parsed)
    except Exception as e:
        logger.error(f"Profile extraction failed: {e}")
        return None


# ─────────────────────────────────────────────
# Wiki writer for enriched profiles
# ─────────────────────────────────────────────

def slugify(text: str) -> str:
    return text.lower().replace(" ", "-").replace("/", "-")[:60]


def write_enriched_profile(profile: EnrichedProfile) -> str:
    """Write an enriched product profile to the wiki, replacing the old profile."""
    competitor_dir = WIKI_ROOT / "competitors" / slugify(profile.competitor)
    competitor_dir.mkdir(parents=True, exist_ok=True)

    filepath = competitor_dir / "profile.md"

    # Build specs table
    specs_lines = ""
    if profile.specs:
        specs_lines = "\n".join(f"| {k} | {v} |" for k, v in profile.specs.items())
        specs_lines = f"| Spec | Value |\n|------|-------|\n{specs_lines}"

    verticals = ", ".join(profile.target_verticals) if profile.target_verticals else "Not specified"
    sources_lines = "\n".join(f"- {url}" for url in profile.sources)

    # Build products section from existing profile if present
    # Read existing profile to preserve product list
    existing_products = ""
    if filepath.exists():
        existing_text = filepath.read_text()
        in_products = False
        product_lines = []
        for line in existing_text.split("\n"):
            if line.strip() == "## Products":
                in_products = True
                continue
            if in_products and line.startswith("## "):
                break
            if in_products:
                product_lines.append(line)
        if product_lines:
            existing_products = "\n".join(product_lines).strip()

    tier_label = "Fury" if profile.product_tier == "fury" else "Nano"

    content = f"""# {profile.competitor} - Competitor Profile

**Last Updated**: {datetime.utcnow().strftime("%Y-%m-%d")}
**Threat Level**: To be assessed
**Tiers**: {tier_label}

---

## Overview

{profile.overview}

## Products

{existing_products if existing_products else f"- **{profile.product_name}** ({tier_label} competitor)"}

## {profile.product_name} Specs

{specs_lines if specs_lines else "No specs extracted."}

**Pricing**: {profile.pricing}
**Availability**: {profile.availability}

## Target Verticals

{verticals}

## Their Positioning

{profile.positioning_language if profile.positioning_language else "No positioning language extracted."}

## HP ZGX Comparison

{profile.hp_comparison_notes if profile.hp_comparison_notes else "No comparison notes extracted."}

## Sources

{sources_lines if sources_lines else "No sources."}
"""
    filepath.write_text(content)
    return str(filepath)


# ─────────────────────────────────────────────
# Main enrich function
# ─────────────────────────────────────────────

async def enrich_product(
    competitor: str,
    product_name: str,
    product_tier: str = "nano",
    url: str | None = None,
) -> dict:
    """
    Full enrichment pipeline for a single product.
    Search -> Fetch -> Extract -> Write to wiki.
    """
    result = {
        "competitor": competitor,
        "product_name": product_name,
        "status": "complete",
    }

    # Step 1: Search and fetch
    sources = await search_for_product(competitor, product_name, url=url)
    result["sources_found"] = len(sources)

    if not sources:
        result["status"] = "failed"
        result["reason"] = "No sources found or fetched"
        return result

    # Step 2: Extract structured profile via LLM
    profile = await extract_profile(competitor, product_name, product_tier, sources)

    if profile is None:
        result["status"] = "failed"
        result["reason"] = "LLM extraction failed"
        return result

    # Step 3: Write to wiki
    filepath = write_enriched_profile(profile)
    result["wiki_path"] = filepath
    result["specs_extracted"] = len(profile.specs)
    result["pricing"] = profile.pricing
    result["availability"] = profile.availability

    return result
