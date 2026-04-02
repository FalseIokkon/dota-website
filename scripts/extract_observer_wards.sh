#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

ENV_FILE="$PROJECT_ROOT/backend/.env"

if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
else
  echo "ERROR: .env file not found at $ENV_FILE"
  exit 1
fi

# Output directory
OUTPUT_DIR="$PROJECT_ROOT/data/exports/wards"
mkdir -p "$OUTPUT_DIR"

sqlite3 -header -csv "$DB_PATH" \
  < "$PROJECT_ROOT/sql/wards/extract_observer_wards.sql" \
  > "$OUTPUT_DIR/extract_observer_wards.csv"

echo "Export complete → $OUTPUT_DIR/extract_observer_wards.csv"