"""
competitive_intel/provenance.py
Tracks the source of every claim in the wiki.
Each competitor product gets a provenance JSON file that maps
individual facts (specs, prices, positioning language) to the
specific URL, date, and context they were extracted from.

Provenance files live alongside profiles:
    data/wiki/competitors/dell/provenance-pro-max-gb300.json

The query endpoint reads these to answer "where did this come from?"
"""

import json
import os
import logging
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel, Field

WIKI_ROOT = Path(os.environ.get("WIKI_ROOT", "/data/wiki"))
logger = logging.getLogger("competitive_intel")


class ClaimRecord(BaseModel):
    """A single factual claim with its source."""
    value: str = Field(description="The claimed value (e.g. '252 GB HBM3e')")
    source_url: str = Field(description="URL where this was found")
    extracted_date: str = Field(description="ISO date when this was extracted")
    context: str = Field(
        default="",
        description="Brief surrounding text or note about where on the page this appeared"
    )


class ProvenanceRecord(BaseModel):
    """Full provenance map for a competitor product."""
    competitor: str
    product_name: str
    last_updated: str
    claims: dict[str, list[ClaimRecord]] = Field(
        description="Map of claim_key -> list of ClaimRecords. "
                    "Multiple records per key when sources disagree or are updated over time. "
                    "Keys match spec names (e.g. 'gpu_memory', 'pricing', 'positioning_language')."
    )


def slugify(text: str) -> str:
    return text.lower().replace(" ", "-").replace("/", "-")[:60]


def _provenance_path(competitor: str, product_name: str) -> Path:
    """Get the path to a product's provenance JSON file."""
    competitor_dir = WIKI_ROOT / "competitors" / slugify(competitor)
    competitor_dir.mkdir(parents=True, exist_ok=True)
    return competitor_dir / f"provenance-{slugify(product_name)}.json"


def load_provenance(competitor: str, product_name: str) -> ProvenanceRecord:
    """Load existing provenance or create empty one."""
    path = _provenance_path(competitor, product_name)
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return ProvenanceRecord(**data)
        except Exception as e:
            logger.warning(f"Failed to load provenance from {path}: {e}")

    return ProvenanceRecord(
        competitor=competitor,
        product_name=product_name,
        last_updated=datetime.utcnow().isoformat(),
        claims={},
    )


def save_provenance(record: ProvenanceRecord) -> str:
    """Save provenance record to disk."""
    path = _provenance_path(record.competitor, record.product_name)
    path.write_text(json.dumps(record.model_dump(), indent=2))
    return str(path)


def add_claim(
    record: ProvenanceRecord,
    claim_key: str,
    value: str,
    source_url: str,
    context: str = "",
) -> None:
    """
    Add a claim to the provenance record.
    If the same value from the same source already exists, skip it.
    If a different value from a different source exists, append it (sources disagree).
    If the same value from a different source exists, append it (corroboration).
    """
    new_claim = ClaimRecord(
        value=value,
        source_url=source_url,
        extracted_date=datetime.utcnow().strftime("%Y-%m-%d"),
        context=context,
    )

    if claim_key not in record.claims:
        record.claims[claim_key] = []

    # Check for exact duplicate (same value + same source)
    for existing in record.claims[claim_key]:
        if existing.value == value and existing.source_url == source_url:
            return  # already recorded

    record.claims[claim_key].append(new_claim)
    record.last_updated = datetime.utcnow().isoformat()


def build_provenance_from_enrichment(
    competitor: str,
    product_name: str,
    profile_data: dict,
    sources: list[dict],
) -> ProvenanceRecord:
    """
    Build or update provenance from an enrichment result.
    Maps each extracted spec/claim to the sources that were used.
    """
    record = load_provenance(competitor, product_name)

    # Determine source URLs that were fed to the model
    source_urls = [s["url"] for s in sources]
    # Use the first source as primary (direct URL if provided)
    primary_url = source_urls[0] if source_urls else "unknown"

    # Record each spec with provenance
    specs = profile_data.get("specs", {})
    for spec_key, spec_value in specs.items():
        if spec_value and spec_value.lower() not in ("unknown", "not specified", "n/a", ""):
            add_claim(
                record,
                claim_key=spec_key,
                value=spec_value,
                source_url=primary_url,
                context=f"Extracted during enrichment from {len(sources)} sources",
            )

    # Record pricing
    pricing = profile_data.get("pricing", "")
    if pricing and pricing.lower() not in ("unknown", ""):
        add_claim(
            record,
            claim_key="pricing",
            value=pricing,
            source_url=primary_url,
            context="Pricing extracted during enrichment",
        )

    # Record availability
    availability = profile_data.get("availability", "")
    if availability and availability.lower() not in ("unknown", ""):
        add_claim(
            record,
            claim_key="availability",
            value=availability,
            source_url=primary_url,
            context="Availability extracted during enrichment",
        )

    # Record positioning language
    positioning = profile_data.get("positioning_language", "")
    if positioning:
        add_claim(
            record,
            claim_key="positioning_language",
            value=positioning,
            source_url=primary_url,
            context="Competitor's marketing language",
        )

    # Record all source URLs as general provenance
    for url in source_urls:
        add_claim(
            record,
            claim_key="_sources_consulted",
            value=url,
            source_url=url,
            context="Source page fetched during enrichment",
        )

    save_provenance(record)
    return record


def build_provenance_from_finding(
    competitor: str,
    product_name: str,
    finding_data: dict,
) -> ProvenanceRecord:
    """
    Build or update provenance from a pipeline Analyst finding.
    """
    record = load_provenance(competitor, product_name)

    source_urls = finding_data.get("source_urls", [])
    primary_url = source_urls[0] if source_urls else "unknown"
    summary = finding_data.get("summary", "")

    # Record the finding summary itself
    category = finding_data.get("category", "general")
    add_claim(
        record,
        claim_key=f"finding_{category}",
        value=summary,
        source_url=primary_url,
        context=f"Analyst finding, confidence: {finding_data.get('confidence', 'unknown')}",
    )

    # Record any specs mentioned
    specs = finding_data.get("specs_mentioned", {})
    for spec_key, spec_value in specs.items():
        if spec_value and spec_value.lower() not in ("unknown", "not specified", ""):
            add_claim(
                record,
                claim_key=spec_key,
                value=spec_value,
                source_url=primary_url,
                context=f"From analyst finding: {summary[:80]}",
            )

    save_provenance(record)
    return record


def format_provenance_for_query(competitor: str, product_name: str) -> str:
    """
    Format provenance as readable text for the query endpoint to include
    in its context when answering questions about sources.
    """
    record = load_provenance(competitor, product_name)

    if not record.claims:
        return f"No provenance data available for {competitor} {product_name}."

    lines = [
        f"# Provenance: {competitor} {product_name}",
        f"Last updated: {record.last_updated}",
        "",
    ]

    for claim_key, claims in record.claims.items():
        if claim_key.startswith("_"):
            continue  # skip internal keys
        lines.append(f"## {claim_key}")
        for c in claims:
            lines.append(f"- **{c.value}**")
            lines.append(f"  Source: {c.source_url}")
            lines.append(f"  Date: {c.extracted_date}")
            if c.context:
                lines.append(f"  Context: {c.context}")
        lines.append("")

    return "\n".join(lines)


def get_all_provenance_files() -> list[Path]:
    """List all provenance JSON files in the wiki."""
    if not WIKI_ROOT.exists():
        return []
    return list(WIKI_ROOT.rglob("provenance-*.json"))
