#!/bin/bash
cd ~/Desktop/competitive-intel-agentic-search

if docker compose ps --format json | grep -q "competitive-intel-vllm"; then
    echo "Stopping competitive intel pipeline..."
    docker compose stop
    echo "GPU memory freed."
else
    echo "Starting competitive intel pipeline..."
    docker compose up -d
    echo "Waiting for vLLM to load model..."
    docker compose logs -f vllm 2>&1 | grep -m1 "Application startup complete"
    echo "Pipeline ready. Run 'ci' to open the dashboard."
fi
