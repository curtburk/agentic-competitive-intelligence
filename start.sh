#!/bin/bash
# start.sh - Run the orchestrator without Docker
# Assumes vLLM and SearXNG are already running separately.
#
# Usage:
#   VLLM_URL=http://localhost:8090/v1 SEARXNG_URL=http://localhost:8888 bash start.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export WIKI_ROOT="${WIKI_ROOT:-${SCRIPT_DIR}/data/wiki}"
export TRACE_DB_PATH="${TRACE_DB_PATH:-${SCRIPT_DIR}/data/traces.db}"
export VLLM_URL="${VLLM_URL:-http://localhost:8090}"
export VLLM_MODEL="${VLLM_MODEL:-Qwen/Qwen3.6-35B-A3B}"
export SEARXNG_URL="${SEARXNG_URL:-http://localhost:8888}"

# Ensure data directories exist
mkdir -p "${WIKI_ROOT}/briefs"
mkdir -p "${WIKI_ROOT}/competitors"
mkdir -p "${WIKI_ROOT}/positioning"
mkdir -p "${WIKI_ROOT}/threats"
mkdir -p "${WIKI_ROOT}/opportunities"

cd "${SCRIPT_DIR}/competitive_intel"

echo "Starting Competitive Intelligence Orchestrator"
echo "  vLLM:    ${VLLM_URL} (model: ${VLLM_MODEL})"
echo "  SearXNG: ${SEARXNG_URL}"
echo "  Wiki:    ${WIKI_ROOT}"
echo "  Traces:  ${TRACE_DB_PATH}"
echo ""

uvicorn orchestrator:app --host 0.0.0.0 --port 8000 --log-level info
