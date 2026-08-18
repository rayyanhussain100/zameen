# CLAUDE.md

Zameen.com property scraper + Q&A agent. Key conventions to keep in mind:

- **src layout**: package code lives under `src/zameen_agent/` (`scraper/`,
  `tools/`, `agent/`). Import as `zameen_agent.*`, not relative to repo root.
- **Storage is Postgres + pgvector**: `db/schema.sql` is the source of truth
  for the data model. `listings.embedding` is `vector(768)` to match Google
  `text-embedding-004`, indexed with `HNSW ... vector_cosine_ops`. Any query
  or write against `embedding` must use the cosine operator (`<=>`) to
  actually hit the index — don't switch to L2/inner-product without also
  changing the index opclass. If you ever change embedding model/dimension,
  the column and index both need migrating.
- **Prices are PKR.** `price_pkr` is always the numeric PKR value; Pakistani
  units (Crore = 1e7, Lakh = 1e5) get parsed in `scraper/normalize.py` —
  don't re-implement ad hoc price parsing elsewhere. Every listing has a
  `purpose` of `'sale'` or `'rent'` — always keep the two distinguishable in
  any query, prompt, or output (rent is periodic, sale is one-time).
- **The scraper must stay polite.** `scraper/client.py`'s `PoliteHTTPClient`
  is the only sanctioned way to fetch Zameen.com pages: it checks
  `robots.txt`, enforces `min_delay + jitter` between requests, and retries
  with exponential backoff via `tenacity`. Don't add a second HTTP path that
  bypasses these. No headless browser, no third-party scraping service —
  `httpx` + `selectolax` only.
- **`parser.py` CSS selectors are placeholders.** They're marked
  `# TODO(selectors)` because they were written without inspecting a live
  Zameen.com page. Don't guess real selectors from training data — inspect
  the live DOM before replacing them. JSON-LD parsing is preferred when
  present since it's less brittle than class-name selectors.
- **`raw` JSONB always stores the full scraped record.** This lets
  `normalize.py` be re-run against existing rows without re-scraping —
  preserve this when touching the pipeline.
- **SQL tool is read-only by construction** (`tools/sql_tool.py`): single
  SELECT statement only, no stacked statements, write/DDL keywords rejected,
  session-level `READ ONLY` transaction. Treat any change here as
  security-sensitive — this is the agent's only path to arbitrary-ish SQL.
