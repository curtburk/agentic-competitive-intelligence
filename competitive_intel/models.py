"""
competitive_intel/models.py
Pydantic models defining typed contracts at every edge of the DAG.
All fields have defaults so missing model output doesn't crash validation.
Field descriptions are preserved to guide the model's structured output.
"""

from pydantic import BaseModel, Field
from datetime import datetime


# ─────────────────────────────────────────────
# SearXNG Response Validation
# ─────────────────────────────────────────────

class SearXNGResult(BaseModel):
    """Single result from SearXNG JSON API."""
    title: str = ""
    url: str = ""
    content: str = ""
    engine: str = ""
    publishedDate: str | None = None
    category: str = "general"


class SearXNGResponse(BaseModel):
    """Validated SearXNG API response."""
    query: str = ""
    results: list[SearXNGResult] = Field(default_factory=list)
    number_of_results: int = 0

    def top_results(self, n: int = 10) -> list[SearXNGResult]:
        return self.results[:n]


# ─────────────────────────────────────────────
# Collector -> Fetcher edge
# ─────────────────────────────────────────────

class SourceItem(BaseModel):
    """A single piece of competitive intelligence from the web."""
    title: str = ""
    url: str = ""
    source_engine: str = ""
    snippet: str = ""
    published_date: str | None = None
    competitor: str = Field(
        default="",
        description="Which competitor this relates to"
    )
    relevance_note: str = Field(
        default="",
        description="Why this result is relevant to HP competitive positioning"
    )


class CollectorOutput(BaseModel):
    """Structured output from the Collector agent."""
    queries_executed: list[str] = Field(default_factory=list)
    sources: list[SourceItem] = Field(default_factory=list)
    sources_skipped: int = Field(
        default=0,
        description="Count of results filtered as irrelevant"
    )


# ─────────────────────────────────────────────
# Fetcher -> Analyst edge
# ─────────────────────────────────────────────

class FetchedSource(BaseModel):
    """A source enriched with full article text via trafilatura."""
    title: str = ""
    url: str = ""
    competitor: str = ""
    snippet: str = ""
    full_text: str | None = Field(
        default=None,
        description="Full article text extracted by trafilatura. "
                    "None if fetch failed or content was behind a paywall."
    )
    fetch_status: str = Field(
        default="failed",
        description="'success', 'failed', 'timeout', or 'blocked'"
    )
    word_count: int = 0
    relevance_note: str = ""


class FetcherOutput(BaseModel):
    """Sources enriched with full article content."""
    sources: list[FetchedSource] = Field(default_factory=list)
    fetch_success_rate: float = Field(
        default=0.0,
        description="Percentage of URLs successfully fetched (0.0 to 1.0)"
    )


# ─────────────────────────────────────────────
# Analyst -> Strategist edge
# ─────────────────────────────────────────────

class CompetitorFinding(BaseModel):
    """A structured finding about a specific competitor."""
    competitor: str = Field(
        default="",
        description="Which competitor this finding is about"
    )
    category: str = Field(
        default="general",
        description="Type of finding",
        examples=[
            "product_launch",
            "pricing_change",
            "partnership",
            "benchmark_claim",
            "customer_win",
            "positioning_shift",
        ]
    )
    summary: str = Field(
        default="",
        description="What was announced or claimed, in 2-3 sentences"
    )
    specs_mentioned: dict[str, str] = Field(
        default_factory=dict,
        description="Key specs if applicable (e.g. VRAM, TOPS, price)"
    )
    target_verticals: list[str] = Field(
        default_factory=list,
        description="Which verticals this targets"
    )
    source_urls: list[str] = Field(
        default_factory=list,
        description="URLs where this information was found"
    )
    confidence: str = Field(
        default="medium",
        description="high/medium/low based on source quality"
    )


class AnalystOutput(BaseModel):
    """Structured extraction from raw source material."""
    findings: list[CompetitorFinding] = Field(default_factory=list)
    competitors_covered: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(
        default_factory=list,
        description="Competitors with no new findings"
    )


# ─────────────────────────────────────────────
# Strategist -> Writer edge
# ─────────────────────────────────────────────

class PositioningComparison(BaseModel):
    """How a competitor's positioning compares to HP's."""
    competitor: str = Field(
        default="",
        description="Which competitor this comparison is about"
    )
    their_narrative: str = Field(
        default="",
        description="Their core positioning claim in one sentence"
    )
    hp_advantage: str = Field(
        default="",
        description="Where HP/ZGX is stronger"
    )
    hp_gap: str = Field(
        default="",
        description="Where HP/ZGX is weaker or silent"
    )
    recommended_response: str = Field(
        default="",
        description="What Curtis should say in customer conversations"
    )


class ThreatOpportunity(BaseModel):
    """A strategic threat or opportunity identified."""
    type: str = Field(
        default="threat",
        description="'threat' or 'opportunity'"
    )
    description: str = Field(
        default="",
        description="What the threat or opportunity is"
    )
    urgency: str = Field(
        default="watch",
        description="'immediate', 'near_term', 'watch'"
    )
    affected_verticals: list[str] = Field(
        default_factory=list,
        description="Which verticals are affected"
    )


class StrategistOutput(BaseModel):
    """Strategic analysis comparing findings to HP positioning."""
    positioning_comparisons: list[PositioningComparison] = Field(default_factory=list)
    threats_and_opportunities: list[ThreatOpportunity] = Field(default_factory=list)
    narrative_health: str = Field(
        default="Not assessed",
        description=(
            "Overall assessment: is 'Compliance by Architecture' "
            "still differentiated, or are competitors closing the gap?"
        )
    )


# ─────────────────────────────────────────────
# Writer output (final deliverable)
# ─────────────────────────────────────────────

class CompetitiveBrief(BaseModel):
    """The final deliverable: a prose summary with actionable takeaways.
    Structured competitive data (findings, positioning, threats) lives
    in the Analyst and Strategist outputs and is written to the wiki
    directly. The Writer's job is synthesis and talking points only."""
    run_id: str = Field(
        default="",
        description="Unique identifier for this pipeline run"
    )
    executive_summary: str = Field(
        default="",
        description="3-5 sentence overview for quick consumption"
    )
    talking_points: list[str] = Field(
        default_factory=list,
        description="Ready-to-use lines for customer conversations"
    )
    changes_since_last_run: str = Field(
        default="First run",
        description="What changed compared to the previous brief"
    )