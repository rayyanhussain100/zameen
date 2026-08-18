# Zameen Agent

Scrapes Zameen.com property listings into Postgres (with pgvector), and
answers natural-language questions over them via a Google ADK agent backed
by two tools: a guardrailed read-only SQL tool and a pgvector semantic
search tool.

- **Scraper**: self-hosted, `httpx` + `selectolax` — no headless browser, no
  third-party scraping API. Honors `robots.txt`, rate-limits with jitter,
  retries with exponential backoff.
- **Storage**: PostgreSQL + pgvector, `listings` table, HNSW index over
  768-dim embeddings (cosine distance) matching Google `text-embedding-004`.
- **Agent**: Google ADK, picks between `sql_query` (exact filters/aggregates)
  and `semantic_search` (fuzzy/descriptive queries) per question. Prices are
  PKR; listings are `sale` or `rent`.

## Repo layout

```
db/schema.sql                       Postgres schema: pgvector extension, listings table, HNSW index
docker-compose.yml                  Local Postgres+pgvector
src/zameen_agent/
  config.py                         Settings (env-driven)
  db.py                             psycopg connection helper (registers pgvector adapter)
  embeddings.py                     text-embedding-004 wrapper
  scraper/
    client.py                       Polite httpx client (robots.txt, rate limit, retry/backoff)
    parser.py                       JSON-LD-first / CSS-fallback listing parser (TODOs — see below)
    normalize.py                    PKR price + Marla/Kanal area parsing -> listings row
    pipeline.py                     fetch -> parse -> normalise -> embed -> upsert; CLI entrypoint
  tools/
    sql_tool.py                     Read-only, single-SELECT-only SQL tool
    semantic_search_tool.py         Embed query + pgvector cosine search
  agent/
    agent.py                        root_agent = ADK Agent wired to both tools
    prompts.py                      System instruction
    run.py                          Interactive terminal chat loop
```

## Setup

1. **Postgres**

   ```bash
   cp .env.example .env   # fill in GOOGLE_API_KEY at minimum
   docker compose up -d
   ```

   This starts `pgvector/pgvector:pg16` and applies `db/schema.sql` on first
   boot (mounted into `/docker-entrypoint-initdb.d/`). To (re)apply manually:

   ```bash
   psql "$DATABASE_URL" -f db/schema.sql
   ```

2. **Python environment**

   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -e .          # or: pip install -r requirements.txt
   ```

3. **Google credentials**

   Set `GOOGLE_API_KEY` in `.env` (used for both the ADK agent's Gemini model
   and `text-embedding-004`). Get a key at https://aistudio.google.com/apikey.

## Usage

Scrape a search-results URL:

```bash
zameen-scrape "https://www.zameen.com/Homes/Lahore-1-1.html" --purpose sale
```

Chat with the agent:

```bash
zameen-agent
```

## Before scraping the live site

- **Read Zameen.com's `robots.txt` and Terms of Service first** and make sure
  scraping is permitted for your use case; `PoliteHTTPClient` checks
  `robots.txt` per-request but that's a courtesy mechanism, not a legal
  opinion.
- `scraper/parser.py`'s CSS-fallback selectors are **placeholders** — they
  are marked `# TODO(selectors)` and will not match real markup. Load a live
  search-results page, inspect the DOM, and fill in real selectors (prefer
  stable attributes like `data-*`/`aria-label`/`itemprop` over generated
  class names). Also verify the actual JSON-LD `@type`(s) Zameen.com emits
  (`_LISTING_JSON_LD_TYPES` in `parser.py` is a guess) — if JSON-LD is
  present and complete, the CSS fallback may rarely be needed.
- Tune `ZAMEEN_MIN_DELAY_SECONDS` / `ZAMEEN_JITTER_SECONDS` conservatively,
  and set a real contact `ZAMEEN_USER_AGENT` so the site owner can reach you
  if there's an issue.

## Data model notes

- Prices are normalised to PKR in `price_pkr` (numeric); `price_raw` keeps
  the original display string. `Crore` = 10,000,000 PKR, `Lakh` = 100,000 PKR.
- Areas: `area_marla` (Kanal is converted to Marla, 1 Kanal = 20 Marla) and
  `area_sqft` are populated independently — Marla↔sqft is **not**
  cross-converted since the ratio varies regionally.
- `raw` (JSONB) always stores the full scraped record, so `normalize.py`
  changes can be replayed against existing rows without re-scraping.
- `embedding` is `vector(768)`, built from title + location + description at
  scrape time (see `embeddings.listing_embedding_text`); queried via cosine
  distance (`<=>`) to match the HNSW `vector_cosine_ops` index.

## Re-embedding

If you change what text gets embedded, or switch embedding models, you'll
need a small backfill script that re-reads `raw`/text columns for existing
rows, calls `embeddings.embed_texts`, and updates `embedding` — not included
yet; `pipeline.py`'s upsert logic is the template for one.
