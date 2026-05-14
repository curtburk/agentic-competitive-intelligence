# Competitive Intelligence Pipeline

An agentic workflow that monitors competitor activity in the on-prem AI hardware space, produces structured competitive briefs, and accumulates findings into a queryable knowledge wiki. Runs entirely on-prem on the HP ZGX Nano at zero marginal cost.

**Hardware**: HP ZGX Nano AI Station (NVIDIA GB10, ARM64, 128GB unified memory)
**Model**: Qwen3.6-35B-A3B + DFlash speculative decoding via vLLM
**Stack**: SearXNG + trafilatura + vLLM + FastAPI + Pydantic

---

## Quick Reference (the stuff you'll forget)

### Starting and stopping

```bash
ci-toggle       # toggle containers on/off (run from any directory on the Nano)
ci              # open the TUI dashboard (run from any directory on the Nano)
```

`ci-toggle` is a toggle switch. If the pipeline is running, it stops it and frees GPU memory. If it's stopped, it starts it and waits for the model to load. You need to stop the pipeline before running other GPU-heavy apps (AI Bridge, demos, etc).

`ci` opens the terminal dashboard in your current SSH session. It does NOT work in VS Code's integrated terminal. Use Windows Terminal SSH instead:

```bash
ssh <YOUR_USER>@<YOUR_ZGX_NANO_IP>
ci
```

### TUI keyboard shortcuts

| Key | Action |
|-----|--------|
| 1 | Latest Brief tab |
| 2 | Query Wiki tab |
| 3 | Enrich Product tab |
| 4 | Run Pipeline tab |
| r | Refresh status + brief |
| q | Quit |
| Tab | Move between input fields |
| Enter | Submit query / trigger action |

### If the TUI shows "DISCONNECTED"

The containers aren't running. Open a VS Code terminal or any SSH session and run:

```bash
ci-toggle
```

Wait for "Pipeline ready" before opening the TUI again.

### If you see "CUDA error: out of memory"

Another GPU app is using the memory. Stop it first:

```bash
docker stop $(docker ps -q)    # stops ALL containers
ci-toggle                       # start the pipeline fresh
```

Or check what's using the GPU:

```bash
nvidia-smi
```

---

## What This System Does

Every time you trigger a run (via the TUI or `curl -X POST http://localhost:8000/run`), the pipeline executes a 5-node directed acyclic graph:

```
Collector -> Fetcher -> Analyst -> Strategist -> Writer
```

1. **Collector**: Runs 52 searches via SearXNG across 8 competitors and 14 tracked products. Pre-filters results by relevance keywords. Passes relevant results to the LLM for structured extraction.

2. **Fetcher**: Takes the Collector's URLs and fetches full article text using trafilatura. No LLM involved, just HTTP fetching and text extraction. Some sites (Supermicro, Gigabyte) block automated fetching. The Analyst still works from snippets when full text isn't available.

3. **Analyst**: Extracts structured competitive findings from the source material. Each finding has a competitor, category, summary, specs, target verticals, source URLs, and confidence level.

4. **Strategist**: Compares analyst findings against HP's positioning (ZGX Nano and Fury specs, "Compliance by Architecture" narrative). Produces head-to-head positioning comparisons, identifies threats and opportunities.

5. **Writer**: Synthesizes everything into an executive summary and ready-to-use talking points. Does NOT generate structured data (that's the Analyst and Strategist's job). Only writes prose.

After the DAG completes, the **Wiki Writer** (a Python function, not an LLM) renders all structured outputs into markdown files in `data/wiki/`.

---

## Competitors Being Tracked

### Fury tier (competes with HP ZGX Fury, ~$100K)

| Competitor | Product | Notes |
|-----------|---------|-------|
| Dell | Pro Max GB300 | Enriched profile with full specs |
| ASUS | ExpertCenter Pro ET900N G3 | |
| NVIDIA | DGX Station | |
| MSI | XpertStation WS300 | |
| MSI | CT60-S8060 | |
| Supermicro | Super AI Station | Bot detection on their site |
| Gigabyte | W775-V10-L01 | Bot detection on their site |
| HPE | ProLiant DL380a | Server-class, indirect competitor |

### Nano tier (competes with HP ZGX Nano, $5,199-$6,030)

| Competitor | Product | Notes |
|-----------|---------|-------|
| Dell | Pro Max GB10 | |
| ASUS | Ascent GX10 | |
| NVIDIA | DGX Spark | |
| MSI | EdgeXpert | ~$3,999 at retail |
| Gigabyte | AI Top ATOM | Bot detection on their site |
| Lenovo | ThinkStation PGX | |

---

## Project Structure

```
competitive-intel-agentic-search/
    ci.py                          # TUI dashboard (run with: python3 ci.py)
    ci-toggle.sh                   # Start/stop containers
    docker-compose.yml             # SearXNG + vLLM + orchestrator
    Dockerfile.orchestrator        # Builds the orchestrator container
    requirements.txt               # Python deps for orchestrator
    start.sh                       # Run orchestrator without Docker (dev only)

    competitive_intel/             # Pipeline source code
        orchestrator.py            # FastAPI app, DAG executor, all endpoints
        models.py                  # Pydantic models for every DAG edge
        agents.py                  # System prompts for all agent nodes
        enrich.py                  # Product profile enrichment endpoint
        wiki.py                    # Wiki writer (renders outputs to markdown)
        query.py                   # Natural language wiki search
        state.py                   # Trace storage (SQLite) + brief reader
        config.py                  # YAML config loader

    config/
        competitors.yml            # Competitors, products, queries, HP positioning

    searxng/
        settings.yml               # SearXNG config (JSON API enabled)

    data/
        wiki/                      # Knowledge wiki (markdown files)
            _index.md              # Auto-generated table of contents
            briefs/                # Weekly competitive briefs
            competitors/           # Per-competitor profiles and findings
                dell/
                    profile.md     # Standing profile (enriched or manual)
                    2026-05-14-*.md  # Pipeline-generated findings
                asus/
                lenovo/
                nvidia/
                msi/
                supermicro/
                gigabyte/
                hpe/
            positioning/           # HP positioning + head-to-head comparisons
                compliance-by-architecture.md  # Core narrative (manual)
                zgx-fury-specs.md              # Fury specs (manual)
                zgx-nano-specs.md              # Nano specs (manual)
                vs-dell.md                     # Pipeline-generated
                vs-asus.md
                ...
            threats/               # Pipeline-identified threats
            opportunities/         # Pipeline-identified opportunities
        traces.db                  # SQLite database of run traces

    tasks/
        todo.md                    # Project task tracking
        lessons.md                 # Architecture decisions and lessons
```

---

## API Endpoints

All endpoints are on port 8000. From any machine on the local network, replace `localhost` with `<YOUR_ZGX_NANO_IP>`.

| Endpoint | Method | What it does | How long it takes |
|----------|--------|-------------|-------------------|
| `/health` | GET | Check if orchestrator + vLLM are up | Instant |
| `/run` | POST | Execute full pipeline (52 searches + 4 LLM calls) | 2-5 minutes |
| `/latest` | GET | Return the most recent weekly brief | Instant |
| `/query` | POST | Ask a question, get answer grounded in wiki | 10-30 seconds |
| `/enrich` | POST | Enrich a specific product profile | 1-3 minutes |
| `/traces/{run_id}` | GET | Get trace data for a specific run | Instant |

### Example curl commands

```bash
# Health check
curl http://localhost:8000/health

# Run full pipeline
curl -X POST http://localhost:8000/run --max-time 600

# Read latest brief
curl http://localhost:8000/latest

# Query the wiki
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "How does Dell Pro Max GB300 compare to HP ZGX Fury?"}'

# Enrich a product profile
curl -X POST http://localhost:8000/enrich \
  -H "Content-Type: application/json" \
  --max-time 300 \
  -d '{
    "competitor": "NVIDIA",
    "product_name": "DGX Spark",
    "product_tier": "nano",
    "url": "https://www.nvidia.com/en-us/products/workstations/dgx-spark/"
  }'

# Check traces from a run
curl http://localhost:8000/traces/56b98ef4
```

---

## Docker Containers

Three containers, all defined in `docker-compose.yml`:

| Container | Image | Port | Purpose |
|-----------|-------|------|---------|
| competitive-intel-searxng | searxng/searxng:latest | 8888 | Metasearch engine (queries Google, Bing, DuckDuckGo) |
| competitive-intel-vllm | vllm/vllm-openai:cu130-nightly | 8091 | LLM inference with DFlash speculative decoding |
| competitive-intel-orchestrator | (built locally) | 8000 | FastAPI pipeline, all endpoints |

vLLM takes 5-10 minutes to load the model on startup. The orchestrator waits for vLLM to be healthy before starting (`depends_on: condition: service_healthy`).

### Rebuilding after code changes

If you edit any Python file in `competitive_intel/`:

```bash
cd ~/Desktop/competitive-intel-agentic-search
docker compose up -d --build orchestrator
```

This rebuilds only the orchestrator container (~1 second) and restarts it. vLLM and SearXNG keep running.

### Checking logs

```bash
docker compose logs orchestrator | tail -30    # recent orchestrator logs
docker compose logs -f orchestrator            # live follow (Ctrl+C to stop)
docker compose logs vllm | tail -10            # vLLM status
docker compose ps                              # container status
```

---

## The Knowledge Wiki

The wiki is just markdown files on disk at `data/wiki/`. You can browse them in VS Code, read them with `cat`, or query them through the `/query` endpoint.

### What writes to the wiki

- **Pipeline runs** (`/run`): Write findings, positioning comparisons, threats, opportunities, and the weekly brief
- **Enrichment** (`/enrich`): Writes or overwrites a competitor's `profile.md`
- **You, manually**: You can create or edit any markdown file directly. The query endpoint will find it.

### File ownership

Files created by the Docker container are owned by root. If you need to delete them:

```bash
sudo rm data/wiki/briefs/old-brief.md
```

### Seeding HP product data

The pipeline can't search for HP's own products (it monitors competitors). You need to manually create and maintain HP's product specs in the wiki so the query endpoint has accurate data to compare against:

- `data/wiki/positioning/compliance-by-architecture.md` - Core narrative
- `data/wiki/positioning/zgx-fury-specs.md` - Fury specs
- `data/wiki/positioning/zgx-nano-specs.md` - Nano specs and pricing

If HP releases updated specs or pricing, edit these files directly.

### Wiping the wiki and starting fresh

If the wiki has stale or bad data:

```bash
docker compose stop orchestrator

# Remove pipeline-generated content (keeps your manually seeded files)
sudo rm -rf data/wiki/briefs/*
sudo rm -rf data/wiki/threats/*
sudo rm -rf data/wiki/opportunities/*
sudo rm -rf data/wiki/competitors/*/2026-*
sudo rm -rf data/wiki/positioning/vs-*
sudo rm -rf data/wiki/_index.md
sudo rm -f data/traces.db

docker compose start orchestrator
```

Then run the pipeline again to rebuild from scratch.

---

## Configuration

All search configuration lives in `config/competitors.yml`. This file is mounted into the orchestrator container, so changes take effect on the next run without rebuilding.

### Adding a new competitor

Add an entry under `competitors:` with their name, query templates, and products:

```yaml
  - name: NewCompany
    tier: nano
    query_templates:
      - "NewCompany AI workstation 2026"
    products:
      - name: "ProductName"
        tier: nano
        queries:
          - "NewCompany ProductName"
          - "NewCompany ProductName specs pricing"
```

Also create a profile in the wiki:

```bash
mkdir -p data/wiki/competitors/newcompany
cat > data/wiki/competitors/newcompany/profile.md << 'EOF'
# NewCompany - Competitor Profile

**Last Updated**: 2026-05-14
**Threat Level**: Unknown
**Tiers**: Nano

---

## Overview

New entrant. Monitoring started.

## Products

- **ProductName** (Nano competitor)
EOF
```

### Tuning search results

In `config/competitors.yml`:

```yaml
search_settings:
  time_range: "week"          # "day", "week", "month", or remove for no filter
  categories: "general,news,it"
  max_results_per_query: 2    # lower = less noise, higher = more coverage
```

### Adding relevance keywords

Results must contain at least one keyword to pass the pre-filter:

```yaml
relevance_keywords:
  - "ai"
  - "inference"
  - "workstation"
  # add more as needed
```

---

## Anti-Hallucination Policy

All agent prompts (Analyst, Strategist, Writer) include strict anti-hallucination instructions:

- NEVER fabricate prices, specs, benchmarks, or performance numbers
- If a price is unknown, say "Unknown" or "pricing not yet confirmed"
- If a spec is not in the source material, omit it entirely
- Every number in a talking point must be traceable to the source data

This was added after the pipeline fabricated an MSI price of $7,999 (actual price: $3,999). The Enricher prompt has similar constraints.

**If you see fabricated numbers in a brief**: the source data was insufficient and the model guessed despite the instructions. Fix it by enriching the relevant product profile with a direct URL to the product page, then re-run the pipeline.

---

## Error Handling

The pipeline doesn't crash silently. Every run returns a status:

| Status | Meaning | What was saved |
|--------|---------|---------------|
| `complete` | All 5 nodes succeeded | Full wiki update + brief |
| `partial` | Some nodes failed | Whatever completed upstream |
| `aborted` | Critical failure early in the DAG | Traces only |

Common failure modes:

| Error | Cause | Fix |
|-------|-------|-----|
| SearXNG returned no results | SearXNG can't reach the internet | Check Nano's network config |
| vLLM HTTP 400 context length | Too many search results for the context window | Reduce `max_results_per_query` in config |
| JSON decode error: Unterminated string | Model output truncated (ran out of tokens) | Reduce `max_results_per_query` |
| Pydantic validation error | Model produced wrong JSON structure | Usually resolves on retry |
| CUDA error: out of memory | Another app is using the GPU | Stop other containers first |

### Checking what went wrong

```bash
# Get the run_id from the /run response, then:
curl http://localhost:8000/traces/<run_id> | python3 -m json.tool

# Or check orchestrator logs directly:
docker compose logs orchestrator | tail -30
```

Each trace shows per-node: latency, input/output tokens, tool calls, validation status, and error messages.

---

## Ports Used

| Port | Service | Conflicts with |
|------|---------|---------------|
| 8888 | SearXNG | Nothing known |
| 8091 | vLLM | Changed from 8090 to avoid conflict with existing vLLM |
| 8000 | Orchestrator | Other FastAPI demos |

If port 8000 conflicts with another demo, change it in `docker-compose.yml`:

```yaml
  orchestrator:
    ports:
      - "8100:8000"    # change host port
```

Then update `API_URL` in `ci.py` to match:

```python
API_URL = "http://localhost:8100"
```

---

## Weekly Workflow

1. SSH into the Nano from Windows Terminal
2. Run `ci-toggle` if the pipeline isn't running
3. Run `ci` to open the dashboard
4. Press `4` to go to Run Pipeline tab
5. Click "Run Full Scan"
6. Wait 2-5 minutes
7. Press `1` to read the latest brief
8. Press `2` to query specific questions
9. Press `3` to enrich any thin product profiles
10. Press `q` to quit when done

Or set up a weekly cron to run automatically:

```bash
crontab -e
# Add:
0 6 * * 1 cd /home/<YOUR_USER>/Desktop/competitive-intel-agentic-search && curl -s -X POST http://localhost:8000/run >> /home/<YOUR_USER>/Desktop/competitive-intel-agentic-search/data/cron.log 2>&1
```

This runs every Monday at 6am. You'd just open the TUI when you want to read results.

---

## Things That Don't Work Yet

- **Narrative drift detection**: No tracking of whether competitor narratives are strengthening or weakening over time
- **Software ecosystem monitoring**: Search queries are hardware-focused, not tracking pre-installed software stacks
- **Analyst report coverage**: Not monitoring Gartner, IDC, Moor Insights publications
- **Active new entrant detection**: Only catches new entrants that appear in generic market queries
- **Enrichment spec extraction**: Some product pages (JS-heavy sites) return empty specs via trafilatura. Direct URLs to static product pages work best.
- **Browser frontend**: TUI only works via SSH in a proper terminal (not VS Code)