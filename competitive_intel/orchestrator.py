"""
competitive_intel/orchestrator.py
DAG executor with Pydantic validation, structured trace logging, and error recovery.
"""

import httpx
import json
import os
import uuid
import time
import logging
import trafilatura
from datetime import datetime
from fastapi import FastAPI
from pydantic import ValidationError

from models import (
    SearXNGResult, SearXNGResponse, CollectorOutput, FetcherOutput, FetchedSource,
    AnalystOutput, StrategistOutput, CompetitiveBrief
)
from agents import collector_prompt, analyst_prompt, strategist_prompt, writer_prompt
from state import load_previous_brief_summary, save_trace, load_traces
from wiki import publish_to_wiki, publish_to_wiki_partial
from query import scan_wiki, build_query_prompt
from config import load_config
from enrich import enrich_product

app = FastAPI(title="Competitive Intelligence Pipeline")

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://searxng:8080")
VLLM_URL = os.environ.get("VLLM_URL", "http://vllm:8000")
VLLM_MODEL = os.environ.get("VLLM_MODEL", "Qwen/Qwen3.6-35B-A3B")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
logger = logging.getLogger("competitive_intel")


# ─────────────────────────────────────────────
# OBSERVABILITY: Structured Trace Logging
# ─────────────────────────────────────────────

class NodeTrace:
    """Captures execution metadata for a single DAG node."""

    def __init__(self, node_name: str, run_id: str):
        self.node_name = node_name
        self.run_id = run_id
        self.start_time = time.monotonic()
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.tool_calls: list[str] = []
        self.validation_passed: bool = False
        self.tool_avoidance: bool = False
        self.error: str | None = None

    def finish(self) -> dict:
        elapsed = time.monotonic() - self.start_time
        trace = {
            "run_id": self.run_id,
            "node": self.node_name,
            "latency_seconds": round(elapsed, 2),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "tool_calls": self.tool_calls,
            "validation_passed": self.validation_passed,
            "tool_avoidance_flag": self.tool_avoidance,
            "error": self.error,
            "timestamp": datetime.utcnow().isoformat(),
        }
        logger.info(json.dumps(trace))
        return trace


# ─────────────────────────────────────────────
# TOOL: trafilatura Full-Text Extraction
# ─────────────────────────────────────────────

def fetch_full_text(url: str) -> tuple[str | None, str]:
    """
    Fetch a URL and extract article text using trafilatura.
    Returns (extracted_text, status_string).
    """
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded is None:
            return None, "failed"
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )
        if text and len(text.strip()) > 50:
            return text.strip(), "success"
        return None, "blocked"
    except Exception as e:
        logger.warning(f"trafilatura fetch failed for {url}: {e}")
        return None, "timeout" if "timeout" in str(e).lower() else "failed"


# ─────────────────────────────────────────────
# TOOL: SearXNG Search (with error handling)
# ─────────────────────────────────────────────

async def search(
    query: str,
    categories: str = "general,news,it",
    time_range: str | None = "week",
) -> SearXNGResponse | None:
    """Query SearXNG and validate response. Returns None if unreachable."""
    try:
        params = {"q": query, "format": "json", "categories": categories}
        if time_range:
            params["time_range"] = time_range

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{SEARXNG_URL}/search", params=params)
            resp.raise_for_status()
            return SearXNGResponse(**resp.json())
    except (httpx.ConnectError, httpx.HTTPStatusError, ValidationError) as e:
        logger.error(f"SearXNG search failed for '{query}': {e}")
        return None


# ─────────────────────────────────────────────
# PRE-FILTER: Keyword relevance gate
# ─────────────────────────────────────────────

def pre_filter_results(
    results: list[SearXNGResult],
    relevance_keywords: list[str],
) -> tuple[list[SearXNGResult], int]:
    """
    Filter search results by checking if title or snippet contains
    at least one relevance keyword. Cuts noise before the LLM sees it.
    Returns (filtered_results, skipped_count).
    """
    if not relevance_keywords:
        return results, 0

    keywords_lower = set(k.lower() for k in relevance_keywords)
    filtered = []
    skipped = 0

    for result in results:
        searchable = f"{result.title} {result.content}".lower()
        if any(kw in searchable for kw in keywords_lower):
            filtered.append(result)
        else:
            skipped += 1

    return filtered, skipped


# ─────────────────────────────────────────────
# AGENT CALLER (with retry and trace)
# ─────────────────────────────────────────────

async def call_agent(
    system_prompt: str,
    user_content: str,
    response_model: type,
    trace: NodeTrace,
    max_retries: int = 1,
) -> dict | None:
    """
    Call vLLM with guided decoding. Retries on failure.
    Returns validated dict on success, None on exhausted retries.
    """
    schema = response_model.model_json_schema()
    last_error = None

    for attempt in range(1 + max_retries):
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{VLLM_URL}/v1/chat/completions",
                    json={
                        "model": VLLM_MODEL,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 4096,
                        "guided_json": json.dumps(schema),
                    },
                )
                resp.raise_for_status()
                result = resp.json()

                usage = result.get("usage", {})
                trace.input_tokens = usage.get("prompt_tokens", 0)
                trace.output_tokens = usage.get("completion_tokens", 0)

                raw = result["choices"][0]["message"]["content"]
                parsed = json.loads(raw)

                # Handle models that use alternative field names
                if response_model.__name__ == "CollectorOutput":
                    # Find the sources list regardless of field name
                    if "sources" not in parsed:
                        for key in list(parsed.keys()):
                            val = parsed[key]
                            if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict):
                                parsed["sources"] = val
                                break

                    # Normalize each source item's field names
                    field_aliases = {
                        "title": ["title", "name", "heading"],
                        "url": ["url", "link", "href", "source_url"],
                        "snippet": ["snippet", "content", "description", "summary", "text", "excerpt"],
                        "competitor": ["competitor", "company", "vendor", "brand"],
                        "relevance_note": ["relevance_note", "relevance", "note", "reason", "why_relevant", "relevance_reason"],
                    }

                    normalized_sources = []
                    for src in parsed.get("sources", []):
                        normalized = {}
                        for target_field, aliases in field_aliases.items():
                            for alias in aliases:
                                if alias in src:
                                    normalized[target_field] = src[alias]
                                    break
                            if target_field not in normalized:
                                normalized[target_field] = ""
                        normalized_sources.append(normalized)

                    parsed["sources"] = normalized_sources

                # Handle StrategistOutput field type mismatches
                if response_model.__name__ == "StrategistOutput":
                    # Remap list names if needed
                    if "positioning_comparisons" not in parsed:
                        for key in list(parsed.keys()):
                            val = parsed[key]
                            if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict) and any(k in val[0] for k in ["competitor", "their_narrative", "narrative"]):
                                parsed["positioning_comparisons"] = val
                                break
                    if "threats_and_opportunities" not in parsed:
                        for key in list(parsed.keys()):
                            val = parsed[key]
                            if isinstance(val, list) and len(val) > 0 and isinstance(val[0], dict) and any(k in val[0] for k in ["type", "urgency", "threat"]):
                                parsed["threats_and_opportunities"] = val
                                break
                    # Coerce list-typed fields to strings
                    for comp in parsed.get("positioning_comparisons", []):
                        for field in ["competitor", "their_narrative", "hp_advantage", "hp_gap", "recommended_response"]:
                            val = comp.get(field)
                            if isinstance(val, list):
                                comp[field] = " ".join(str(v) for v in val)
                    for item in parsed.get("threats_and_opportunities", []):
                        for field in ["type", "description", "urgency"]:
                            val = item.get(field)
                            if isinstance(val, list):
                                item[field] = " ".join(str(v) for v in val)

                # Handle AnalystOutput field type mismatches
                if response_model.__name__ == "AnalystOutput":
                    for finding in parsed.get("findings", []):
                        # specs_mentioned: model sometimes returns list instead of dict
                        specs = finding.get("specs_mentioned", {})
                        if isinstance(specs, list):
                            finding["specs_mentioned"] = {f"spec_{i}": str(v) for i, v in enumerate(specs)}
                        elif not isinstance(specs, dict):
                            finding["specs_mentioned"] = {}

                        # target_verticals: ensure it's a list
                        verts = finding.get("target_verticals", [])
                        if isinstance(verts, str):
                            finding["target_verticals"] = [verts]
                        elif not isinstance(verts, list):
                            finding["target_verticals"] = []

                        # source_urls: ensure it's a list
                        urls = finding.get("source_urls", [])
                        if isinstance(urls, str):
                            finding["source_urls"] = [urls]
                        elif not isinstance(urls, list):
                            finding["source_urls"] = []

                validated = response_model(**parsed)
                trace.validation_passed = True
                return validated.model_dump()

        except httpx.HTTPStatusError as e:
            last_error = f"vLLM HTTP {e.response.status_code}: {e.response.text[:200]}"
            logger.warning(f"[{trace.node_name}] attempt {attempt + 1} failed: {last_error}")
        except json.JSONDecodeError as e:
            last_error = f"JSON decode error: {str(e)[:200]}"
            logger.warning(f"[{trace.node_name}] attempt {attempt + 1} failed: {last_error}")
        except ValidationError as e:
            last_error = f"Pydantic validation: {str(e)[:200]}"
            logger.warning(f"[{trace.node_name}] attempt {attempt + 1} failed: {last_error}")
        except httpx.ConnectError:
            last_error = f"vLLM unreachable at {VLLM_URL}"
            logger.error(f"[{trace.node_name}] vLLM connection failed, no retry")
            break
        except Exception as e:
            last_error = f"Unexpected: {type(e).__name__}: {str(e)[:200]}"
            logger.warning(f"[{trace.node_name}] attempt {attempt + 1} failed: {last_error}")

    trace.error = last_error
    trace.validation_passed = False
    return None


# ─────────────────────────────────────────────
# DAG PIPELINE (with error recovery)
# ─────────────────────────────────────────────

async def run_pipeline(config: dict) -> dict:
    """Execute the full DAG with error recovery."""

    run_id = str(uuid.uuid4())[:8]
    previous_summary = load_previous_brief_summary()
    all_traces = []
    result = {"run_id": run_id, "status": "complete", "nodes_completed": []}

    # === NODE 1: COLLECTOR ===
    trace = NodeTrace("collector", run_id)
    all_sources = []
    queries_executed = []
    search_failures = 0
    pre_filter_skipped = 0

    # Pull search settings from config
    search_settings = config.get("search_settings", {})
    time_range = search_settings.get("time_range", "week")
    categories = search_settings.get("categories", "general,news,it")
    max_per_query = search_settings.get("max_results_per_query", 5)
    relevance_keywords = config.get("relevance_keywords", [])

    async def _execute_query(query: str):
        """Run a single search query and collect results."""
        nonlocal search_failures
        queries_executed.append(query)
        trace.tool_calls.append(f"searxng:{query}")
        search_result = await search(query, categories=categories, time_range=time_range)
        if search_result is None:
            search_failures += 1
            return []
        return search_result.top_results(max_per_query)

    # Layer 1: Competitor-level queries
    for competitor in config["competitors"]:
        comp_name = competitor["name"]
        for query in competitor.get("query_templates", []):
            results = await _execute_query(query)
            all_sources.extend(results)

        # Layer 2: Product-specific queries
        for product in competitor.get("products", []):
            for query in product.get("queries", []):
                results = await _execute_query(query)
                all_sources.extend(results)

    # Layer 3: Market-wide queries (catch new entrants)
    for query in config.get("market_queries", []):
        results = await _execute_query(query)
        all_sources.extend(results)

    if not all_sources:
        trace.error = f"All {search_failures} searches failed. SearXNG may be down."
        all_traces.append(trace.finish())
        save_trace(run_id, all_traces)
        result["status"] = "aborted"
        result["reason"] = "SearXNG returned no results"
        return result

    # Layer 4: Pre-filter by relevance keywords (before LLM sees anything)
    all_sources, pre_filter_skipped = pre_filter_results(all_sources, relevance_keywords)
    if pre_filter_skipped > 0:
        logger.info(f"[collector] Pre-filter: kept {len(all_sources)}, skipped {pre_filter_skipped}")

    if not all_sources:
        trace.error = f"All results filtered as irrelevant ({pre_filter_skipped} skipped)"
        all_traces.append(trace.finish())
        save_trace(run_id, all_traces)
        result["status"] = "aborted"
        result["reason"] = "All search results filtered as irrelevant"
        return result

    collector_input = {
        "search_results": [s.model_dump() for s in all_sources],
        "previous_brief_summary": previous_summary,
        "queries_executed": queries_executed,
    }
    collector_output = await call_agent(
        system_prompt=collector_prompt(),
        user_content=json.dumps(collector_input),
        response_model=CollectorOutput,
        trace=trace,
    )
    if collector_output is None:
        all_traces.append(trace.finish())
        save_trace(run_id, all_traces)
        result["status"] = "aborted"
        result["reason"] = f"Collector agent failed: {trace.error}"
        return result

    all_traces.append(trace.finish())
    result["nodes_completed"].append("collector")

    # === NODE 2: FETCHER (no LLM, pure tool) ===
    trace = NodeTrace("fetcher", run_id)
    fetched_sources = []
    success_count = 0
    for source in collector_output["sources"]:
        full_text, status = fetch_full_text(source["url"])
        trace.tool_calls.append(f"trafilatura:{source['url']}")
        if status == "success":
            success_count += 1
        fetched_sources.append(FetchedSource(
            title=source["title"],
            url=source["url"],
            competitor=source["competitor"],
            snippet=source["snippet"],
            full_text=full_text,
            fetch_status=status,
            word_count=len(full_text.split()) if full_text else 0,
            relevance_note=source["relevance_note"],
        ))

    total = max(len(fetched_sources), 1)
    fetch_rate = round(success_count / total, 2)

    if fetch_rate == 0:
        logger.warning("[fetcher] All URL fetches failed. Analyst will use snippets only.")

    fetcher_output = FetcherOutput(
        sources=fetched_sources,
        fetch_success_rate=fetch_rate,
    ).model_dump()
    trace.validation_passed = True
    all_traces.append(trace.finish())
    result["nodes_completed"].append("fetcher")

    # === NODE 3: ANALYST ===
    trace = NodeTrace("analyst", run_id)
    analyst_output = await call_agent(
        system_prompt=analyst_prompt(),
        user_content=json.dumps(fetcher_output),
        response_model=AnalystOutput,
        trace=trace,
    )
    if analyst_output is None:
        all_traces.append(trace.finish())
        save_trace(run_id, all_traces)
        result["status"] = "aborted"
        result["reason"] = f"Analyst agent failed: {trace.error}"
        return result

    all_traces.append(trace.finish())
    result["nodes_completed"].append("analyst")

    # === NODE 4: STRATEGIST ===
    trace = NodeTrace("strategist", run_id)
    strategist_input = {
        "analyst_findings": analyst_output,
        "hp_positioning": config["hp_positioning"],
    }
    strategist_output = await call_agent(
        system_prompt=strategist_prompt(),
        user_content=json.dumps(strategist_input),
        response_model=StrategistOutput,
        trace=trace,
    )
    if strategist_output is None:
        all_traces.append(trace.finish())
        save_trace(run_id, all_traces)
        publish_to_wiki_partial(analyst_output=analyst_output)
        result["status"] = "partial"
        result["reason"] = f"Strategist failed: {trace.error}. Analyst findings saved to wiki."
        return result

    all_traces.append(trace.finish())
    result["nodes_completed"].append("strategist")

    # === NODE 5: WRITER ===
    trace = NodeTrace("writer", run_id)
    writer_input = {
        "strategist_analysis": strategist_output,
        "previous_brief_summary": previous_summary,
        "run_id": run_id,
    }
    brief = await call_agent(
        system_prompt=writer_prompt(),
        user_content=json.dumps(writer_input),
        response_model=CompetitiveBrief,
        trace=trace,
    )
    all_traces.append(trace.finish())

    if brief is None:
        save_trace(run_id, all_traces)
        publish_to_wiki(brief=None, analyst_output=analyst_output, strategist_output=strategist_output)
        result["status"] = "partial"
        result["reason"] = f"Writer failed: {trace.error}. Findings and positioning saved to wiki."
        return result

    result["nodes_completed"].append("writer")

    # Full success: save everything
    save_trace(run_id, all_traces)
    wiki_files = publish_to_wiki(brief, analyst_output, strategist_output)
    logger.info(f"Wiki updated: {len(wiki_files)} files written")

    return result


# ─────────────────────────────────────────────
# API ENDPOINTS
# ─────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check for the orchestrator."""
    return {"status": "ok", "model": VLLM_MODEL, "searxng": SEARXNG_URL}


@app.post("/run")
async def trigger_run():
    """Trigger a competitive intelligence run."""
    config = load_config("/config/competitors.yml")
    result = await run_pipeline(config)
    return result


@app.get("/latest")
async def get_latest():
    """Return the most recent weekly brief from the wiki."""
    from pathlib import Path
    briefs_dir = Path(os.environ.get("WIKI_ROOT", "/data/wiki")) / "briefs"
    if not briefs_dir.exists():
        return {"status": "no runs yet"}
    brief_files = sorted(briefs_dir.glob("*.md"), reverse=True)
    if not brief_files:
        return {"status": "no runs yet"}
    return {"brief": brief_files[0].read_text(), "file": brief_files[0].name}


@app.get("/traces/{run_id}")
async def get_traces_endpoint(run_id: str):
    """Return trace data for a specific run for debugging."""
    traces = load_traces(run_id)
    if not traces:
        return {"status": "no traces found"}
    return traces


@app.post("/query")
async def query_wiki(request: dict):
    """
    Natural language query over the competitive intelligence wiki.

    Body: {"question": "What has Dell announced about data sovereignty?"}
    Returns: {"answer": "...", "sources": [...]}
    """
    question = request.get("question", "")
    if not question:
        return {"error": "No question provided"}

    wiki_pages = scan_wiki(question, max_files=10)

    if not wiki_pages:
        return {
            "answer": "No relevant findings in the wiki for this query.",
            "sources": [],
        }

    prompt = build_query_prompt(question, wiki_pages)

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{VLLM_URL}/v1/chat/completions",
                json={
                    "model": VLLM_MODEL,
                    "messages": [
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.2,
                    "max_tokens": 2048,
                },
            )
            resp.raise_for_status()
            answer = resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return {"error": f"vLLM query failed: {str(e)[:200]}", "sources": []}

    return {
        "answer": answer,
        "sources": [
            {"path": p["path"], "title": p["title"], "score": p["score"]}
            for p in wiki_pages
        ],
    }


@app.post("/enrich")
async def enrich_endpoint(request: dict):
    """
    Enrich a competitor product profile by searching the web,
    fetching product pages, and extracting structured specs.

    Body: {
        "competitor": "Dell",
        "product_name": "Pro Max GB10",
        "product_tier": "nano",
        "url": "https://dell.com/..."  (optional, direct product page)
    }
    Returns: {"status": "complete", "specs_extracted": 8, ...}
    """
    competitor = request.get("competitor", "")
    product_name = request.get("product_name", "")
    product_tier = request.get("product_tier", "nano")
    url = request.get("url")

    if not competitor or not product_name:
        return {"error": "Both 'competitor' and 'product_name' are required"}

    if product_tier not in ("nano", "fury"):
        return {"error": "product_tier must be 'nano' or 'fury'"}

    result = await enrich_product(
        competitor=competitor,
        product_name=product_name,
        product_tier=product_tier,
        url=url,
    )
    return result


@app.get("/provenance/{competitor}/{product_name}")
async def get_provenance(competitor: str, product_name: str):
    """
    Get the provenance map for a specific competitor product.
    Shows where every claim came from (URL, date, context).

    Example: GET /provenance/Dell/Pro%20Max%20GB300
    """
    from provenance import load_provenance
    record = load_provenance(competitor, product_name)
    if not record.claims:
        return {"status": "no provenance data", "competitor": competitor, "product_name": product_name}
    return record.model_dump()

