"""File indexer.

Provides a CLI and programmatic API to build and (re)index the `file`
index in Elasticsearch from the IGSR database.

This module:
  * Reads ES settings/mappings from a local JSON file.
  * Fetches files and transforms rows into ES documents.
  * Creates or updates the ES index via bulk operations.

The script uses Click for the CLI and is safe to import for use from
other modules.
"""

# ──────────────────────────────────────────────────────────────
# Imports
# ──────────────────────────────────────────────────────────────

import click
import json
from typing import Any, Optional
import time
from elasticsearch.helpers import BulkIndexError
from index.elasticsearch_indexer import ElasticSearchIndexer
from .fetch_information_from_db import FetchFileFromDB
from index.config_read import read_from_config_file


# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────

json_file = "index/file_index/file.json"


# ──────────────────────────────────────────────────────────────
# Indexer
# ──────────────────────────────────────────────────────────────


class FileIndexer:
    """Indexer for the `file` index."""

    def __init__(self, config_file: str, es_host: Optional[str], type_of: str, dry_run: bool = False):
        """Initialise the indexer.

        Args:
            config_file (str): Path to the configuration file with DB credentials.
            es_host (str | None): Elasticsearch host (overrides config if provided).
            type_of (str): Operation type, either "create" or "update".
        """
        self.config_file = config_file
        self.es_host = es_host
        self.type_of = type_of
        self.dry_run = bool(dry_run)
        self._data = None
        self._fetcher = None
        self._indexer = None

    @property
    def data(self):
        """Lazily-loaded configuration data."""
        if self._data is None:
            self._data = read_from_config_file(self.config_file)
        return self._data

    @property
    def fetcher(self):
        """Lazily-built DB fetcher."""
        if self._fetcher is None:
            self._fetcher = FetchFileFromDB(self.data)
        return self._fetcher

    @property
    def indexer(self):
        """Lazily-built Elasticsearch indexer."""
        if self._indexer is None:
            es_cfg = (self.data.get("elasticsearch") or {})
            self._indexer = ElasticSearchIndexer(
                self.es_host or es_cfg.get("host"),
                "file",
                es_api_key=es_cfg.get("api_key"),
                es_username=es_cfg.get("username"),
                es_password=es_cfg.get("password"),
                es_cloud_id=es_cfg.get("cloud_id"),
            )
        return self._indexer

    def load_json_file(self) -> dict[str, Any]:
        """Load index settings and mappings from JSON."""
        with open(json_file, "r") as file:
            data = json.load(file)
        return data

    def create_file_index(self) -> bool:
        """Create the `file` index."""
        json_data = self.load_json_file()
        return self.indexer.create_index(json_data["settings"], json_data["mappings"])

    def generate_actions(self, rows):
        """Generate bulk actions for indexing."""
        file_ids = [int(r[0]) for r in rows]
        dc_data, sp_data = self.fetcher.preload_data(file_ids)

        for row in rows:
            padded_id = f"{int(row[0]):09d}"  # match legacy ES v1.5 IDs
            files_data = self.fetcher.populate_the_dictionary(row, dc_data, sp_data)
            yield self.indexer.index_data(files_data, padded_id, self.type_of)

    def build_and_index_file_info(self):
        """Build and bulk-index all eligible files."""
        t0 = time.time()
        click.echo(f"[info] Index: file — mode: {self.type_of} — dry_run: {'yes' if self.dry_run else 'no'}")

        rows = self.fetcher.fetch_files()
        total_rows = len(rows)
        click.echo(f"[info] Found {total_rows} candidate document(s) from DB")
        if not rows:
            click.echo("[info] Nothing to do — exiting")
            return

        click.echo("[info] Preparing bulk actions…")
        actions = []
        for i, action in enumerate(self.generate_actions(rows), 1):
            actions.append(action)
            if i % 500 == 0:
                click.echo(f"[info] Prepared {i}/{total_rows} actions…")

        click.echo(f"[info] Prepared {len(actions)} action(s)")
        if not actions:
            click.echo("[warn] No actions to send — exiting")
            return

        try:
            if self.type_of == "create":
                if self.dry_run:
                    click.echo("[dry-run] Would drop & recreate index from on-disk settings/mappings")
                    click.echo(f"[dry-run] Would upsert {len(actions)} document(s)")
                    click.echo("[dry-run] Would set indexed_in_elasticsearch=1 for eligible DB rows")
                    return
                spec = self.load_json_file()
                click.echo("[info] Dropping & recreating index…")
                self.indexer.ensure_fresh_index(spec["settings"], spec["mappings"])
                self.indexer.bulk_index(actions)
                click.echo(f"[ok] Bulk indexing successful ({len(actions)} docs) in {time.time()-t0:.1f}s")
            else:
                if self.dry_run:
                    click.echo("[dry-run] Would verify index existence; if missing, exit with warning")
                    click.echo(f"[dry-run] Would upsert {len(actions)} document(s)")
                    click.echo("[dry-run] Would update indexed_in_elasticsearch flags in DB")
                    return
                if not self.indexer.index_exists():
                    click.echo("[warn] Update requested but index 'file' does not exist. No changes made. Run once with --type_of=create.")
                    return
                click.echo("[info] Upserting into existing index…")
                self.indexer.bulk_index(actions)
                click.echo(f"[ok] Bulk indexing successful ({len(actions)} docs) in {time.time()-t0:.1f}s")

            # keep indexed_in_elasticsearch db column in sync with ES
            if not self.dry_run:
                t_sync = time.time()
                updated = self.fetcher.update_elasticsearch_file()
                if isinstance(updated, int):
                    click.echo(f"[ok] DB flag sync: indexed_in_elasticsearch updated for {updated} row(s) in {time.time()-t_sync:.1f}s")
                else:
                    click.echo(f"[ok] DB flag (indexed_in_elasticsearch) sync completed, {len(actions)} rows set to 1")
        except BulkIndexError as e:
            click.echo("[error] Bulk indexing failed")
            errs = getattr(e, "errors", [])
            if errs:
                click.echo(f"[error] Items with errors: {len(errs)}")
                for err in errs[:5]:
                    click.echo(err)
                if len(errs) > 5:
                    click.echo(f"[error] … and {len(errs)-5} more")


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────


@click.command()
@click.option(
    "--config_file",
    "-c",
    type=click.Path(exists=True),
    help="Configuration file",
    required=True,
)
@click.option("--es_host", "-es", type=str, help="Elasticsearch host (overrides config)", required=False)
@click.option(
    "--type_of", "-t", type=str, help="Update or create an index", required=True
)
@click.option("--dry_run/--no-dry_run", default=False, help="Log actions without touching Elasticsearch")
def create_data(config_file: str, es_host: Optional[str], type_of: str, dry_run: bool):
    """CLI entry point to build and index file documents."""
    file_indexer = FileIndexer(config_file, es_host, type_of, dry_run=dry_run)
    file_indexer.build_and_index_file_info()


# ──────────────────────────────────────────────────────────────
# Script entry
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    create_data()