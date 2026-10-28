#!/usr/bin/env bash
# Usage: scripts/run_exp.sh <run_name> [extra -c configs...]
# Runs the 50-instance subset (resumable; waits out relay outages and reruns failed instances),
# then evaluates with the SWE-bench harness and prints stats.
set -euo pipefail
cd "$(dirname "$0")/.."
name=$1; shift
filter="^($(paste -sd'|' configs/subset_verified_50.txt))$"
total=$(grep -c . configs/subset_verified_50.txt)
extra=(); for c in "$@"; do extra+=(-c "$c"); done
key=$(grep OPENAI_API_KEY ~/.config/mini-swe-agent/.env | cut -d"'" -f2)
py() { MSWEA_SILENT_STARTUP=1 .venv/bin/python -I "$@"; }

relay_up() {
    curl -s -m 40 https://xhyapi.com/v1/chat/completions -H "Authorization: Bearer $key" -H "Content-Type: application/json" \
        -d '{"model":"deepseek-v4-pro","messages":[{"role":"user","content":"hi"}],"max_tokens":5}' | grep -q '"choices"'
}

for round in $(seq 1 20); do
    until relay_up; do echo "[$(date +%T)] relay down, waiting"; sleep 120; done
    MSWEA_SILENT_STARTUP=1 .venv/bin/mini-extra swebench --subset verified --split test --filter "$filter" \
        -c swebench.yaml -c configs/deepseek.yaml "${extra[@]}" -o "runs/$name" -w 8 || true
    done_n=$(py scripts/drop_failed.py "runs/$name")
    echo "[$(date +%T)] round $round: $done_n/$total submitted"
    [ "$done_n" -ge "$total" ] && break
done
[ "$done_n" -ge "$total" ] || { echo "only $done_n/$total submitted after 20 rounds"; exit 1; }

mkdir -p runs/eval && (cd runs/eval && ../../.venv-eval/bin/python -I -m swebench.harness.run_evaluation \
    --dataset_name SWE-bench/SWE-bench_Verified --predictions_path "../$name/preds.json" --max_workers 8 --run_id "$name")

py scripts/stats.py "runs/$name" --report "$(ls runs/eval/*."$name".json)"
