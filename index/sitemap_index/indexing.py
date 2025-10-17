"""Sitemap indexer

Reads site + DB config, discovers pages via the sitemap fetcher, and indexes
them into Elasticsearch in batches. Supports a 'create' mode (create index on
first bulk) and 'update' mode (bulk only).
"""

# ──────────────────────────────────────────────────────────────
# Imports
# ──────────────────────────────────────────────────────────────

import click, json, hashlib, os
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit
from index.elasticsearch_indexer import ElasticSearchIndexer
from index.config_read import read_from_config_file
from .fetch_information_from_site import FetchSitemapFromSite

# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────

JSON_PATH = "index/sitemap_index/sitemap.json"

# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _canon_url(u: str) -> str:
    """Canonicalize a URL: drop fragment, normalize index.html, strip trailing slash."""
    s = urlsplit(u)
    path = s.path[:-10] if s.path.endswith("/index.html") else (s.path[:-10] if s.path.endswith("index.html") else s.path)
    if path and path != "/" and path.endswith("/"):
        path = path[:-1]
    return urlunsplit((s.scheme, s.netloc, path, s.query, ""))

def _doc_id_from_url(u: str) -> str:
    """Stable ES _id from canonical URL (SHA-1 hex)."""
    return hashlib.sha1(_canon_url(u).encode("utf-8")).hexdigest()

def _cfg_get(cfg: dict[str, Any], key: str, default: Any) -> Any:
    """
    Read indexer options from config, with fallbacks:
      1) raw key in config
      2) 'sitemap_<key>' in config
      3) ENV IGSR_SITEMAP_<KEY>
      4) provided default
    """
    if key in cfg:
        return cfg[key]
    skey = f"sitemap_{key}"
    if skey in cfg:
        return cfg[skey]
    envv = os.getenv(f"IGSR_SITEMAP_{key.upper()}")
    return envv if envv is not None else default

# ──────────────────────────────────────────────────────────────
# Indexer
# ──────────────────────────────────────────────────────────────

class SitemapIndexer:
    def __init__(self, config_file: str, es_host: Optional[str], type_of: str):
        self.cfg = read_from_config_file(config_file)

        # Indexer options (config/env overrideable; sensible defaults)
        self.index_name = str(_cfg_get(self.cfg, "index_name", "sitemap"))
        self.batch_size = int(_cfg_get(self.cfg, "batch_size", 1000))
        self.max_docs   = int(_cfg_get(self.cfg, "max_docs", 0)) or None
        self.refresh    = str(_cfg_get(self.cfg, "refresh", "false")).lower() in ("1", "true", "yes", "on")
        self.dry_run    = str(_cfg_get(self.cfg, "dry_run", "false")).lower() in ("1", "true", "yes", "on")

        es_cfg = (self.cfg.get("elasticsearch") or {})
        self.es = ElasticSearchIndexer(
            es_host or es_cfg.get("host"),
            self.index_name,
            es_api_key=es_cfg.get("api_key"),
            es_username=es_cfg.get("username"),
            es_password=es_cfg.get("password"),
            es_cloud_id=es_cfg.get("cloud_id"),
        )

        self.type_of = type_of
        self.fetcher = FetchSitemapFromSite(self.cfg)

    def _load_spec(self) -> dict[str, Any]:
        with open(JSON_PATH, "r") as fh:
            return json.load(fh)

    def _create_index(self) -> None:
        """Create index using on-disk spec; ignore existence result (idempotent)."""
        spec = self._load_spec()
        self.es.create_index(spec["settings"], spec["mappings"])

    def build_and_index(self):
        do_create = (self.type_of == "create")

        # Materialize docs once so we can announce a precise count beforehand.
        rows = list(self.fetcher.iter_docs())
        if self.max_docs:
            rows = rows[: self.max_docs]

        click.echo(f"Preparing {len(rows)} sitemap document(s) to index...")

        actions = []
        seen_urls: set[str] = set()
        n_indexed = 0

        for doc in rows:
            url = _canon_url(doc["url"])
            if url in seen_urls:
                continue
            seen_urls.add(url)

            _id = _doc_id_from_url(url)
            if not self.dry_run:
                actions.append(self.es.index_data(doc, _id, self.type_of))
                if len(actions) >= self.batch_size:
                    if do_create:
                        self._create_index()
                        do_create = False
                    self.es.bulk_index(actions)
                    n_indexed += len(actions)
                    actions.clear()
            else:
                # Dry-run: pretend we indexed it (no network calls).
                n_indexed += 1

        # Flush any remaining actions
        if not self.dry_run and actions:
            if do_create:
                self._create_index()
                do_create = False
            self.es.bulk_index(actions)
            n_indexed += len(actions)
            actions.clear()

        # Optional refresh (best-effort)
        if self.refresh and not self.dry_run:
            try:
                # If your ElasticSearchIndexer doesn't implement refresh_index, this is a no-op due to try/except
                self.es.refresh_index()  # type: ignore[attr-defined]
            except Exception:
                pass

        click.echo(f"Bulk indexing successful — indexed={n_indexed} (index={self.index_name})")

# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

@click.command()
@click.option("--config_file", "-c", type=click.Path(exists=True), required=True, help="Configuration file")
@click.option("--es_host", "-es", type=str, required=False, help="Elasticsearch host (overrides config)")
@click.option("--type_of", "-t", type=str, required=True, help="Update or create an index")
def create_data(config_file: str, es_host: Optional[str], type_of: str):
    idx = SitemapIndexer(config_file, es_host, type_of)
    idx.build_and_index()

if __name__ == "__main__":
    create_data()