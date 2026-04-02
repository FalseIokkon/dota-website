#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

ENV_FILE="$PROJECT_ROOT/.env"

if [ -f "$ENV_FILE" ]; then
  set -a
  source "$ENV_FILE"
  set +a
else
  echo "ERROR: .env file not found at $ENV_FILE"
  exit 1
fi

mkdir -p "$PROJECT_ROOT/backend/sql/wards/csv"

sqlite3 -header -csv "$DB_PATH" \
  < "$PROJECT_ROOT/backend/sql/wards/extract_observer_wards.sql" \
  > "$PROJECT_ROOT/backend/sql/wards/csv/extract_observer_wards.csv"

echo "Export complete → $PROJECT_ROOT/backend/sql/wards/csv/extract_observer_wards.csv"