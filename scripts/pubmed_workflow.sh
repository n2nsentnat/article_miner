#!/usr/bin/env bash
# Collect PubMed JSON, then run duplicate detection in one step.
# Requires: uv, project dependencies (uv sync). Network access for NCBI.
#
# Usage:
#   ./scripts/pubmed_workflow.sh [options] QUERY
# Options must appear before the query. The query may be multiple words.
#
# Examples:
#   ./scripts/pubmed_workflow.sh "diabetes mellitus[tiab]"
#   ./scripts/pubmed_workflow.sh -n 50 -d ./out/my_run "COVID-19[tiab]"
#
# Optional env: NCBI_API_KEY, NCBI_EMAIL (passed through to collect-pubmed via process env).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1

COUNT=100
OUT_DIR=""

usage() {
  echo "pubmed_workflow.sh — collect PubMed JSON, then run duplicate detection." >&2
  echo "Usage: $0 [-n COUNT] [-d DIR] QUERY..." >&2
  echo "  -n, --count   Max articles to collect (default: 100)" >&2
  echo "  -d, --dir     Output directory (default: workflow_YYYYMMDD_HHMMSS under repo root)" >&2
  echo "  -h, --help    Show this help" >&2
}

while [[ $# -gt 0 ]]; do
  case "${1:-}" in
    -n | --count)
      COUNT="${2:-}"
      shift 2
      ;;
    -d | --dir)
      OUT_DIR="${2:-}"
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage
      exit 2
      ;;
    *)
      break
      ;;
  esac
done

QUERY="$*"
if [[ -z "${QUERY// }" ]]; then
  echo "error: QUERY is required (PubMed / Entrez search string)." >&2
  usage
  exit 2
fi

if [[ -z "$OUT_DIR" ]]; then
  OUT_DIR="${ROOT}/workflow_$(date +%Y%m%d_%H%M%S)"
fi

mkdir -p "$OUT_DIR"
ARTICLES="${OUT_DIR}/articles.json"
DUPES_JSON="${OUT_DIR}/dupes.json"
DUPES_MD="${OUT_DIR}/dupes.md"

echo "==> Collecting (max ${COUNT}) -> ${ARTICLES}"
uv run collect-pubmed "$QUERY" -n "$COUNT" -o "$ARTICLES"

echo "==> Finding probable duplicates -> ${DUPES_JSON} , ${DUPES_MD}"
uv run find-pubmed-dupes "$ARTICLES" -o "$DUPES_JSON" -m "$DUPES_MD"

echo "Done. Output directory: ${OUT_DIR}"
echo "  articles: ${ARTICLES}"
echo "  dupes JSON: ${DUPES_JSON}"
echo "  dupes Markdown: ${DUPES_MD}"
