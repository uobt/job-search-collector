#!/usr/bin/env bash
# Полный цикл сбора: JobSpy → CSV → импорт SQLite → экспорт.
# Использование: ./bin/collect.sh "Data Scientist" 25 "London, UK" 14 [stem]
set -euo pipefail

QUERY="${1:-Sales Development Representative}"
RESULTS="${2:-10}"
LOCATION="${3:-London, UK}"
DAYS="${4:-14}"
STEM="${5:-run_$(date +%Y%m%d_%H%M%S)}"

cd "$(dirname "$0")/.."
mkdir -p data/logs

if command -v uv >/dev/null 2>&1; then
    PY="uv run --python 3.12 python"
else
    PY="python"
fi

echo "[$(date -Is)] collect: query='$QUERY' results=$RESULTS location='$LOCATION' days=$DAYS"

$PY pilots/jobspy_pilot.py "$QUERY" "$RESULTS" "$LOCATION" "$DAYS" --out "$STEM"

CSV="data/pilot/${STEM}.csv"
if [ ! -s "$CSV" ]; then
    echo "[$(date -Is)] пустая выдача — импорт пропущен"
    exit 2
fi

$PY -m jobcollector import --source linkedin --file "$CSV"
$PY -m jobcollector import --source indeed   --file "$CSV"
$PY -m jobcollector export --format csv --out "data/export/${STEM}.csv"
$PY -m jobcollector status
echo "[$(date -Is)] done: data/export/${STEM}.csv"
