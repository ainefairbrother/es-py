"""Data Collections indexer.

Provides a CLI and programmatic API to build and (re)index the
`data_collections` index in Elasticsearch from the IGSR database.

This module:
  * Reads ES settings/mappings from a local JSON file.
  * Fetches data collections and transforms rows into ES documents.
  * Creates or updates the ES index via bulk operations.

The script uses Click for the CLI and is safe to import for use from
other modules (see `run()`).
"""

# ──────────────────────────────────────────────────────────────
# Imports
# ──────────────────────────────────────────────────────────────

import click
from typing import Any, Optional
import json
import time
from index.elasticsearch_indexer import ElasticSearchIndexer
from .fetch_information_from_db import DCDetailsFetcher
from index.config_read import read_from_config_file
from elasticsearch.helpers import BulkIndexError


# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────

json_file = "index/data_collection_index/data_collections.json"


# ──────────────────────────────────────────────────────────────
# Indexer
# ──────────────────────────────────────────────────────────────


class DataCollectionsIndexer:
    """Index builder for data collections.

    Constructs and executes bulk actions for the `data_collections` index,
    using settings/mappings from disk and documents sourced from the DB.

    Attributes:
        type_of: Whether to 'create' the index (fresh) or 'update' it.
        data: Database configuration loaded from the provided config file.
        fetcher: Helper to fetch and shape rows from the database.
        indexer: Elasticsearch helper targeting the `data_collections` index.
    """

    def __init__(self, config_file: str, es_host: Optional[str], type_of: str, dry_run: bool = False):
        """Initialise the indexer.

        Args:
            config_file: Path to the YAML/JSON configuration file.
            es_host (str | None): Elasticsearch host (overrides config if provided).
            type_of: Operation mode, either 'create' or 'update'.
        """
        self.type_of = type_of
        self.dry_run = bool(dry_run)
        self.data = read_from_config_file(config_file)
        self.fetcher = DCDetailsFetcher(self.data)

        es_cfg = (self.data.get("elasticsearch") or {})
        self.indexer = ElasticSearchIndexer(
            es_host or es_cfg.get("host"),
            "data_collections",
            es_api_key=es_cfg.get("api_key"),
            es_username=es_cfg.get("username"),
            es_password=es_cfg.get("password"),
            es_cloud_id=es_cfg.get("cloud_id"),
        )

    def load_json_file(self) -> dict[str, Any]:
        """Load index settings and mappings.

        Returns:
            A dict containing the JSON document with `settings` and `mappings`.
        """
        with open(json_file, "r") as file:
            data = json.load(file)
        return data

    def create_data_collections_index(self) -> bool:
        """Create the `data_collections` index.

        Returns:
            True if the index was created successfully; otherwise False.
        """
        json_data = self.load_json_file()
        data_collection = self.indexer.create_index(
            json_data["settings"], json_data["mappings"]
        )
        return data_collection

    def build_and_index_datacollections(self):
        """Build and bulk-index all data collections.

        Fetches rows from the database, converts them into ES actions, and
        performs a bulk index. On 'create', the index is created beforehand.

        Raises:
            BulkIndexError: If the bulk indexing operation fails.
        """
        t0 = time.time()
        click.echo(f"[info] Index: data_collections — mode: {self.type_of} — dry_run: {'yes' if self.dry_run else 'no'}")

        rows = self.fetcher.fetch_datacollections()
        total_rows = len(rows)
        click.echo(f"[info] Found {total_rows} candidate document(s) from DB")
        if not rows:
            click.echo("[info] Nothing to do — exiting")
            return

        actions = []
        skipped_no_code = 0

        click.echo("[info] Preparing bulk actions…")
        for i, row in enumerate(rows, 1):
            code = row[1]
            if not code:
                skipped_no_code += 1
                continue

            dc_data = self.fetcher.populate_the_dictionary_structure(row)
            actions.append(self.indexer.index_data(dc_data, code, self.type_of))

            if i % 500 == 0:
                click.echo(f"[info] Prepared {i}/{total_rows} actions…")

        click.echo(f"[info] Prepared {len(actions)} action(s); skipped {skipped_no_code} row(s) without a code")
        if not actions:
            click.echo("[warn] No actions to send — exiting")
            return

        try:
            if self.type_of == "create":
                if self.dry_run:
                    click.echo("[dry-run] Would drop & recreate index from on-disk settings/mappings")
                    click.echo(f"[dry-run] Would upsert {len(actions)} document(s)")
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
                    return
                if not self.indexer.index_exists():
                    click.echo("[warn] Update requested but index 'data_collections' does not exist. No changes made. Run once with --type_of=create.")
                    return
                click.echo("[info] Upserting into existing index…")
                self.indexer.bulk_index(actions)
                click.echo(f"[ok] Bulk indexing successful ({len(actions)} docs) in {time.time()-t0:.1f}s")
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
    """Create or update the `data_collections` index via CLI."""
    dc_indexer = DataCollectionsIndexer(config_file, es_host, type_of, dry_run=dry_run)
    dc_indexer.build_and_index_datacollections()


if __name__ == "__main__":
    create_data()


# ──────────────────────────────────────────────────────────────
# Programmatic API
# ──────────────────────────────────────────────────────────────


def run(config_file, es_host, type_of):
    """Programmatic entry point for indexing."""
    indexer = DataCollectionsIndexer(config_file, es_host, type_of)
    result = indexer.build_and_index_datacollections()