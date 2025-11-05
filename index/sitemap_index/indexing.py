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
import time
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
    def __init__(self, config_file: str, es_host: Optional[str], type_of: str, dry_run: bool = False):
        self.cfg = read_from_config_file(config_file)

        # Indexer options (config/env overrideable; sensible defaults)
        self.index_name = str(_cfg_get(self.cfg, "index_name", "sitemap"))
        self.batch_size = int(_cfg_get(self.cfg, "batch_size", 1000))
        self.max_docs   = int(_cfg_get(self.cfg, "max_docs", 0)) or None
        self.refresh    = str(_cfg_get(self.cfg, "refresh", "false")).lower() in ("1", "true", "yes", "on")

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
        self.dry_run = bool(dry_run)
        self.fetcher = FetchSitemapFromSite(self.cfg)

    def _load_spec(self) -> dict[str, Any]:
        with open(JSON_PATH, "r") as fh:
            return json.load(fh)

    def _create_fresh(self) -> None:
        spec = self._load_spec()
        self.es.ensure_fresh_index(spec["settings"], spec["mappings"])

    def build_and_index(self):
        t0 = time.time()
        click.echo(f"[info] Index: {self.index_name} — mode: {self.type_of} — dry_run: {'yes' if self.dry_run else 'no'}")

        rows = list(self.fetcher.iter_docs())
        if self.max_docs:
            rows = rows[: self.max_docs]

        click.echo(f"[info] Found {len(rows)} candidate sitemap document(s) to index")
        click.echo("[info] Preparing bulk actions…")

        actions = []
        seen_urls: set[str] = set()

        for i, doc in enumerate(rows, 1):
            url = _canon_url(doc["url"])
            if url in seen_urls:
                continue
            seen_urls.add(url)

            _id = _doc_id_from_url(url)
            actions.append(self.es.index_data(doc, _id, self.type_of))
            if len(actions) % self.batch_size == 0:
                click.echo(f"[info] Prepared {len(actions)}/{len(rows)} actions so far…")

        click.echo(f"[info] Prepared {len(actions)} action(s)")
        if not actions:
            click.echo("[info] Nothing to do — exiting")
            return

        if self.type_of == "create":
            if self.dry_run:
                click.echo("[dry-run] Would drop & recreate index from on-disk settings/mappings")
                click.echo(f"[dry-run] Would upsert {len(actions)} document(s) in batches of {self.batch_size}")
                return
            click.echo("[info] Dropping & recreating index…")
            self._create_fresh()
            # bulk in batches
            for start in range(0, len(actions), self.batch_size):
                end = start + self.batch_size
                self.es.bulk_index(actions[start:end])
            click.echo(f"[ok] Bulk indexing successful ({len(actions)} docs) in {time.time()-t0:.1f}s")
        else:
            if self.dry_run:
                click.echo("[dry-run] Would verify index existence; if missing, exit with warning")
                click.echo(f"[dry-run] Would upsert {len(actions)} document(s) in batches of {self.batch_size}")
                return
            if not self.es.index_exists():
                click.echo(f"[warn] Update requested but index '{self.index_name}' does not exist. No changes made. Run once with --type_of=create.")
                return
            click.echo("[info] Upserting into existing index…")
            for start in range(0, len(actions), self.batch_size):
                end = start + self.batch_size
                self.es.bulk_index(actions[start:end])
            click.echo(f"[ok] Bulk indexing successful ({len(actions)} docs) in {time.time()-t0:.1f}s")

        if self.refresh and not self.dry_run:
            try:
                self.es.refresh_index()  # type: ignore[attr-defined]
            except Exception:
                pass


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

@click.command()
@click.option("--config_file", "-c", type=click.Path(exists=True), required=True, help="Configuration file")
@click.option("--es_host", "-es", type=str, required=False, help="Elasticsearch host (overrides config)")
@click.option("--type_of", "-t", type=str, required=True, help="Update or create an index")
@click.option("--dry_run/--no-dry_run", default=False, help="Log actions without touching Elasticsearch")
def create_data(config_file: str, es_host: Optional[str], type_of: str, dry_run: bool):
    idx = SitemapIndexer(config_file, es_host, type_of, dry_run=dry_run)
    idx.build_and_index()

if __name__ == "__main__":
    create_data()