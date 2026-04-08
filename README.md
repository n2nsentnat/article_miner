# Article miner (PubMed JSON collector)

Command-line tool that searches [PubMed](https://pubmed.ncbi.nlm.nih.gov/) via the [NCBI E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25500/) (`esearch` + `efetch`), applies rate limiting and retries, and writes **flat, validated JSON** suitable for downstream pipelines.

## Requirements

- Python **3.13**
- [uv](https://docs.astral.sh/uv/) for environments and dependency management

## Setup

```bash
cd article_miner
uv sync --all-groups
```

## Usage

```bash
uv run python collect.py "machine learning" --count 100 --output results.json
```

Equivalent:

```bash
uv run python -m article_miner "cancer immunotherapy" --count 50 --output out.json
```

After install, the console script `collect-pubmed` is also available:

```bash
uv run collect-pubmed "diabetes" -n 20 -o diabetes.json
```

### Options

| Option | Meaning |
|--------|---------|
| `QUERY` (positional) | Entrez/PubMed query string |
| `-n`, `--count` | Maximum articles to retrieve (default: 100) |
| `-o`, `--output` | Output JSON path (required) |
| `--api-key` | NCBI API key; same as env `NCBI_API_KEY` |
| `--email` | Contact email; same as env `NCBI_EMAIL` (recommended by NCBI) |
| `--tool` | Tool name sent to NCBI (default: `article_miner`) |

### API key and rate limits

Without an API key, the client spaces requests for roughly **3 requests per second**. With a key, roughly **10 per second** (see [NCBI usage guidelines](https://www.ncbi.nlm.nih.gov/books/NBK25497/)).

Switching is a single flag or environment variable:

```bash
export NCBI_API_KEY=your_key_here
uv run python collect.py "query" -n 500 -o out.json
# or
uv run python collect.py "query" -n 500 -o out.json --api-key your_key_here
```

## Output JSON

The file is a single object:

- `query`, `total_match_count`, `requested_count`, `retrieved_count`
- `articles`: list of records with stable fields such as `pmid`, `title`, `abstract`, `authors`, `doi`, `journal_full`, `mesh_terms`, `keywords`, etc.
- `warnings`: non-fatal issues (for example PMIDs that did not return parseable XML)

All article objects are validated with **Pydantic** before serialization.

## Behavior notes

- **Search pagination**: `esearch` returns at most **10,000** IDs per call; larger requests use multiple pages.
- **Detail batches**: `efetch` IDs are requested in batches (default **200** per call) to stay within practical limits.
- **Errors**: Transient HTTP failures and 5xx responses use bounded retries with backoff; repeated **429** responses surface as a clear error. Malformed JSON/XML yields `MalformedResponseError`-style messages at the CLI.

## Architecture

Layers follow **Clean / Onion** style dependency direction (inward-only):

| Layer | Role |
|-------|------|
| **Domain** | `Article`, `CollectionOutput`, domain exceptions — no I/O |
| **Application** | `CollectArticlesService` + `PubMedGateway` port (protocol) |
| **Infrastructure** | NCBI `EntrezPubMedGateway`, `ResilientHttpClient`, `RateLimiter`, XML/JSON parsing |
| **CLI** | Typer composition root: wires config → HTTP → gateway → use case |

**SOLID**: single-purpose modules, gateway depends on `HttpTextClient` protocol for testing, use case depends on `PubMedGateway` protocol — not on `httpx` or URLs.

## Development

```bash
uv sync --all-groups
uv run pytest
```

## License

Add your license here.
