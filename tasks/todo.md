# Competitive Intelligence Pipeline - TODO

## Phase 1: Foundation (current)
- [x] models.py - Pydantic models for all DAG edges
- [x] agents.py - System prompts for all four agent nodes
- [x] config.py - YAML config loader
- [x] state.py - Trace persistence (SQLite) + wiki-based brief state
- [x] wiki.py - Wiki writer with partial save support
- [x] query.py - Natural language wiki search
- [x] orchestrator.py - Full DAG executor with error recovery
- [x] docker-compose.yml - SearXNG + vLLM (DFlash) + orchestrator
- [x] Dockerfile.orchestrator
- [x] competitors.yml - HP positioning + competitor list
- [x] SearXNG settings.yml
- [x] Competitor _profile.md files (Dell, Lenovo, Lambda, Supermicro, HPE)
- [x] HP positioning wiki page (compliance-by-architecture.md)
- [x] start.sh

## Phase 2: Testing
- [ ] Bring up SearXNG container, test with curl
- [ ] Bring up vLLM with DFlash, verify model loads
- [ ] Test Collector node in isolation (SearXNG -> Collector)
- [ ] Test Fetcher node (trafilatura on known competitor URLs)
- [ ] Test Analyst node (feed mock FetcherOutput, check schema)
- [ ] Test Strategist node (feed mock AnalystOutput + HP positioning)
- [ ] Test Writer node (feed mock StrategistOutput)
- [ ] End-to-end: POST /run, inspect wiki output and traces
- [ ] Test /query endpoint against seeded wiki content
- [ ] Test guided_json compatibility with nested Pydantic schemas

## Phase 3: Iteration
- [ ] Tune search query templates based on SearXNG results
- [ ] Evaluate DFlash + guided_json interaction
- [ ] Add wiki deduplication (match on competitor + category + key terms)
- [ ] Consider RSS feeds for competitors with JS-heavy sites
- [ ] Set up weekly cron trigger
