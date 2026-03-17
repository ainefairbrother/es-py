#!/usr/bin/env bash
set -euo pipefail

# Create the IGSR Elasticsearch indices in Elastic Cloud from the IGSR database.
# This script validates the supplied config.ini against the requested environment
# and then runs the documented index creation workflow in sequence.
# Use --dry-run first to verify the commands that will be executed.
#
# Examples:
#   deploy_igsr_es_indices.sh --path ./es-py --env dev --config ./scripts/dev_config.ini --dry-run
#   deploy_igsr_es_indices.sh --path ./es-py --env dev --config ./scripts/dev_config.ini --use-prod-db
#   deploy_igsr_es_indices.sh --path /full/path/to/es-py --env prod --config /full/path/to/config.ini

PROJECT_ROOT=""

CONFIG_PATH=""
TARGET_ENV=""
BRANCH_NAME="unknown"
PYTHON_BIN="python3"
DRY_RUN=0
USE_PROD_DB=0

EXPECTED_CLOUD_MARKER=""
EXPECTED_DB_NAME=""
EXPECTED_SITE_MARKER=""
FORBIDDEN_SITE_MARKER=""

ES_CLOUD_ID=""
ES_API_KEY=""
DB_HOST=""
DB_PORT=""
DB_USER=""
DB_NAME=""
SITE_ROOT=""
SITE_BASE=""

INDEX_MODULES=(
  "index.population_index.indexing"
  "index.analysis_group_index.indexing"
  "index.data_collection_index.indexing"
  "index.file_index.indexing"
  "index.sample_index.indexing"
  "index.super_population_index.indexing"
  "index.sitemap_index.indexing"
)

log() { printf "\n==> %s\n" "$*"; }
die() { printf "\nERROR: %s\n" "$*" >&2; exit 1; }

usage() {
  cat <<EOF
Usage: $(basename "$0") --path PATH --env {dev|prod} --config PATH [--dry-run]

Required:
  --path, -p PATH      Path to es-py
  --env, -e ENV        Target environment: dev or prod
  --config, -c PATH    Path to config.ini for the selected environment

Optional:
  --dry-run            Print the validation summary and commands without executing
  --use-prod-db        Allow --env dev to use the production database name
  -h, --help           Show help

Examples:
  $(basename "$0") --path ./es-py --env dev --config ./scripts/dev_config.ini --dry-run
  $(basename "$0") --path ./es-py --env dev --config ./scripts/dev_config.ini --use-prod-db
  $(basename "$0") --path /full/path/to/es-py --env prod --config /full/path/to/config.ini
EOF
}

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf "DRY RUN: "
    printf "%q " "$@"
    printf "\n"
    return 0
  fi
  "$@"
}

run_in_dir() {
  local dir="$1"
  shift

  if [ "$DRY_RUN" -eq 1 ]; then
    printf "DRY RUN: (cd %q && " "$dir"
    printf "%q " "$@"
    printf ")\n"
    return 0
  fi

  (
    cd "$dir"
    "$@"
  )
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command not found: $1"
}

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf "%s" "$value"
}

strip_matching_quotes() {
  local value="$1"
  local first_char=""
  local last_char=""

  if [ "${#value}" -ge 2 ]; then
    first_char="${value:0:1}"
    last_char="${value: -1}"
    if { [ "$first_char" = "\"" ] || [ "$first_char" = "'" ]; } && [ "$first_char" = "$last_char" ]; then
      value="${value:1:${#value}-2}"
    fi
  fi

  printf "%s" "$value"
}

to_lower() {
  printf "%s" "$1" | tr '[:upper:]' '[:lower:]'
}

read_ini_value() {
  local section="$1"
  local key="$2"
  local value=""

  value="$(
    awk -v target_section="$(to_lower "$section")" -v target_key="$(to_lower "$key")" '
      function ltrim(s) { sub(/^[[:space:]]+/, "", s); return s }
      function rtrim(s) { sub(/[[:space:]]+$/, "", s); return s }
      function trim(s)  { return rtrim(ltrim(s)) }

      /^[[:space:]]*[#;]/ || /^[[:space:]]*$/ { next }

      /^[[:space:]]*\[/ {
        section_name = $0
        gsub(/^[[:space:]]*\[/, "", section_name)
        gsub(/\][[:space:]]*$/, "", section_name)
        current_section = tolower(trim(section_name))
        next
      }

      current_section == target_section {
        split_pos = index($0, "=")
        if (split_pos == 0) {
          next
        }

        key_name = tolower(trim(substr($0, 1, split_pos - 1)))
        if (key_name != target_key) {
          next
        }

        value = trim(substr($0, split_pos + 1))
        print value
        exit
      }
    ' "$CONFIG_PATH"
  )"

  value="$(trim "$value")"
  value="$(strip_matching_quotes "$value")"
  printf "%s" "$value"
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --path|-p)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        PROJECT_ROOT="$2"
        shift 2
        ;;
      --env|-e)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        TARGET_ENV="$2"
        shift 2
        ;;
      --config|-c)
        [ "$#" -ge 2 ] || die "Missing value for $1"
        CONFIG_PATH="$2"
        shift 2
        ;;
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      --use-prod-db)
        USE_PROD_DB=1
        shift
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "Unknown argument: $1"
        ;;
    esac
  done
}

validate_inputs() {
  [ -n "$PROJECT_ROOT" ] || die "--path is required"
  [ -n "$TARGET_ENV" ] || die "--env is required"
  [ -n "$CONFIG_PATH" ] || die "--config is required"
  [ -d "$PROJECT_ROOT" ] || die "Path does not exist: $PROJECT_ROOT"
  [ -f "$CONFIG_PATH" ] || die "Config file does not exist: $CONFIG_PATH"

  PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd -P)"
  CONFIG_PATH="$(cd "$(dirname "$CONFIG_PATH")" && pwd -P)/$(basename "$CONFIG_PATH")"
  [ -f "$PROJECT_ROOT/pyproject.toml" ] || die "Project root does not look like es-py: $PROJECT_ROOT"

  case "$TARGET_ENV" in
    dev|prod) ;;
    *)
      die "--env must be 'dev' or 'prod' (got: $TARGET_ENV)"
      ;;
  esac

  if [ "$USE_PROD_DB" -eq 1 ] && [ "$TARGET_ENV" = "prod" ]; then
    die "--use-prod-db can only be used with --env dev"
  fi
}

set_env_values() {
  case "$TARGET_ENV" in
    dev)
      EXPECTED_CLOUD_MARKER="prj-ext-dev-gaa-igsr"
      EXPECTED_DB_NAME="igsr_website_v2_test"
      EXPECTED_SITE_MARKER="test.internationalgenome.org"
      FORBIDDEN_SITE_MARKER=""
      if [ "$USE_PROD_DB" -eq 1 ]; then
        EXPECTED_DB_NAME="igsr_website_v2"
      fi
      ;;
    prod)
      EXPECTED_CLOUD_MARKER="prj-ext-prod-gaa-igsr"
      EXPECTED_DB_NAME="igsr_website_v2"
      EXPECTED_SITE_MARKER="internationalgenome.org"
      FORBIDDEN_SITE_MARKER="test.internationalgenome.org"
      ;;
  esac
}

load_config() {
  ES_CLOUD_ID="$(read_ini_value "elasticsearch" "cloud_id")"
  [ -n "$ES_CLOUD_ID" ] || ES_CLOUD_ID="$(read_ini_value "elasticsearch" "ES_CLOUD_ID")"

  ES_API_KEY="$(read_ini_value "elasticsearch" "api_key")"
  [ -n "$ES_API_KEY" ] || ES_API_KEY="$(read_ini_value "elasticsearch" "ES_API_KEY")"

  DB_HOST="$(read_ini_value "database" "host")"
  DB_PORT="$(read_ini_value "database" "port")"
  DB_USER="$(read_ini_value "database" "user")"
  DB_NAME="$(read_ini_value "database" "name")"
  SITE_ROOT="$(read_ini_value "site" "site_root")"
  SITE_BASE="$(read_ini_value "site" "site_base")"

  [ -n "$ES_CLOUD_ID" ] || die "Missing [elasticsearch] cloud_id (or ES_CLOUD_ID) in: $CONFIG_PATH"
  [ -n "$ES_API_KEY" ] || die "Missing [elasticsearch] api_key (or ES_API_KEY) in: $CONFIG_PATH"
  [ -n "$DB_HOST" ] || die "Missing [database] host in: $CONFIG_PATH"
  [ -n "$DB_PORT" ] || die "Missing [database] port in: $CONFIG_PATH"
  [ -n "$DB_USER" ] || die "Missing [database] user in: $CONFIG_PATH"
  [ -n "$DB_NAME" ] || die "Missing [database] name in: $CONFIG_PATH"
  [ -n "$SITE_ROOT" ] || die "Missing [site] site_root in: $CONFIG_PATH"
  [ -n "$SITE_BASE" ] || die "Missing [site] site_base in: $CONFIG_PATH"
}

validate_config_for_env() {
  local es_cloud_id_lc=""
  local db_name_lc=""
  local site_root_lc=""
  local site_base_lc=""

  es_cloud_id_lc="$(to_lower "$ES_CLOUD_ID")"
  db_name_lc="$(to_lower "$DB_NAME")"
  site_root_lc="$(to_lower "$SITE_ROOT")"
  site_base_lc="$(to_lower "$SITE_BASE")"

  case "$es_cloud_id_lc" in
    *"$EXPECTED_CLOUD_MARKER"*) ;;
    *)
      die "Config does not match --env $TARGET_ENV: cloud_id must contain '$EXPECTED_CLOUD_MARKER'"
      ;;
  esac

  if [ "$db_name_lc" != "$(to_lower "$EXPECTED_DB_NAME")" ]; then
    die "Config does not match --env $TARGET_ENV: expected database name '$EXPECTED_DB_NAME' but found '$DB_NAME'"
  fi

  case "$site_root_lc" in
    *"$EXPECTED_SITE_MARKER"*) ;;
    *)
      die "Config does not match --env $TARGET_ENV: site_root must contain '$EXPECTED_SITE_MARKER'"
      ;;
  esac

  case "$site_base_lc" in
    *"$EXPECTED_SITE_MARKER"*) ;;
    *)
      die "Config does not match --env $TARGET_ENV: site_base must contain '$EXPECTED_SITE_MARKER'"
      ;;
  esac

  if [ -n "$FORBIDDEN_SITE_MARKER" ]; then
    case "$site_root_lc" in
      *"$FORBIDDEN_SITE_MARKER"*)
        die "Config does not match --env $TARGET_ENV: site_root must not contain '$FORBIDDEN_SITE_MARKER'"
        ;;
    esac

    case "$site_base_lc" in
      *"$FORBIDDEN_SITE_MARKER"*)
        die "Config does not match --env $TARGET_ENV: site_base must not contain '$FORBIDDEN_SITE_MARKER'"
        ;;
    esac
  fi
}

warn_database_selection() {
  printf "\nWARNING: This run will read from database '%s' on host '%s:%s'.\n" "$DB_NAME" "$DB_HOST" "$DB_PORT"

  if [ "$TARGET_ENV" = "dev" ] && [ "$USE_PROD_DB" -eq 1 ]; then
    printf "WARNING: --use-prod-db is enabled, so --env dev will use the production database.\n"
  fi
}

detect_branch() {
  if ! command -v git >/dev/null 2>&1; then
    BRANCH_NAME="git-not-installed"
    return 0
  fi

  if ! git -C "$PROJECT_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    BRANCH_NAME="not-a-git-repo"
    return 0
  fi

  BRANCH_NAME="$(git -C "$PROJECT_ROOT" branch --show-current 2>/dev/null || true)"
  if [ -z "$BRANCH_NAME" ]; then
    BRANCH_NAME="detached-head"
  fi
}

print_plan() {
  local index_module=""

  log "Index creation plan"
  printf "PROJECT_ROOT=%s\n" "$PROJECT_ROOT"
  printf "CONFIG_PATH=%s\n" "$CONFIG_PATH"
  printf "TARGET_ENV=%s\n" "$TARGET_ENV"
  printf "BRANCH_NAME=%s\n" "$BRANCH_NAME"
  printf "PYTHON_BIN=%s\n" "$PYTHON_BIN"
  printf "USE_PROD_DB=%s\n" "$USE_PROD_DB"
  printf "ES_CLOUD_ID=%s\n" "$ES_CLOUD_ID"
  printf "DB_HOST=%s\n" "$DB_HOST"
  printf "DB_PORT=%s\n" "$DB_PORT"
  printf "DB_USER=%s\n" "$DB_USER"
  printf "DB_NAME=%s\n" "$DB_NAME"
  printf "SITE_ROOT=%s\n" "$SITE_ROOT"
  printf "SITE_BASE=%s\n" "$SITE_BASE"
  printf "INDEX_MODE=create\n"
  printf "INDEX_ORDER=\n"

  for index_module in "${INDEX_MODULES[@]}"; do
    printf "  - %s\n" "$index_module"
  done
}

run_indexers() {
  local index_module=""

  for index_module in "${INDEX_MODULES[@]}"; do
    log "Running $index_module"
    run_in_dir "$PROJECT_ROOT" \
      "$PYTHON_BIN" -m "$index_module" \
      --config_file "$CONFIG_PATH" \
      --type_of create
  done
}

main() {
  parse_args "$@"
  validate_inputs
  set_env_values
  load_config
  warn_database_selection
  validate_config_for_env
  detect_branch

  if [ "$DRY_RUN" -eq 0 ]; then
    need_cmd "$PYTHON_BIN"
  fi

  print_plan
  run_indexers

  log "Done"
}

main "$@"
