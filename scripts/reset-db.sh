#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

DB_CONTAINER_ID="$(docker compose ps -q db || true)"
if [[ -z "${DB_CONTAINER_ID}" ]]; then
  echo "Database container not found. Start it first: docker compose up -d db"
  exit 1
fi

DB_IS_RUNNING="$(docker inspect -f '{{.State.Running}}' "${DB_CONTAINER_ID}" 2>/dev/null || echo "false")"
if [[ "${DB_IS_RUNNING}" != "true" ]]; then
  echo "Database container is not running. Start it first: docker compose up -d db"
  exit 1
fi

clear_dir_contents() {
  local target_dir="$1"
  mkdir -p "${target_dir}"
  shopt -s nullglob dotglob
  local entries=("${target_dir}"/*)
  shopt -u nullglob dotglob
  if (( ${#entries[@]} > 0 )); then
    rm -rf "${entries[@]}"
  fi
}

echo "Clearing all rows in public schema tables (keeping table structures)..."

docker compose exec -T db psql -U user -d agent_cv -v ON_ERROR_STOP=1 -c "
DO \$\$
DECLARE
    truncate_sql text;
BEGIN
    SELECT
        'TRUNCATE TABLE ' ||
        string_agg(format('%I.%I', schemaname, tablename), ', ') ||
        ' RESTART IDENTITY CASCADE'
    INTO truncate_sql
    FROM pg_tables
    WHERE schemaname = 'public';

    IF truncate_sql IS NOT NULL THEN
        EXECUTE truncate_sql;
    END IF;
END
\$\$;
"

echo "Clearing local file data in ./data/cache and ./data/uploads..."
clear_dir_contents "${REPO_ROOT}/data/cache"
clear_dir_contents "${REPO_ROOT}/data/uploads"

echo "Done. Database tables are empty, and data/cache + data/uploads are cleared."
