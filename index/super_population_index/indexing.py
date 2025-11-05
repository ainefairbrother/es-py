"""Superpopulation indexer.

Provides a CLI and programmatic API to build and (re)index the
`superpopulation` index in Elasticsearch from the IGSR database.

This module:
  * Reads ES settings/mappings from a local JSON file.
  * Fetches superpopulation data and transforms rows into ES documents.
  * Creates or updates the ES index via bulk operations.
"""

# ──────────────────────────────────────────────────────────────
# Imports
# ──────────────────────────────────────────────────────────────

import click
import json
import time
from typing import Any, Optional
from index.elasticsearch_indexer import ElasticSearchIndexer
from .fetch_information_from_db import FetchSPFromDB
from index.config_read import read_from_config_file


# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────

json_file = "index/super_population_index/superpopulations_mappings.json"


# ──────────────────────────────────────────────────────────────
# Indexer
# ──────────────────────────────────────────────────────────────


class SuperPopulationIndexer:
    """Indexer for the `superpopulation` index."""

    def __init__(self, config_file: str, es_host: Optional[str], type_of: str, dry_run: bool = False):
        """Initialise the indexer.

        Args:
            config_file (str): Path to configuration file.
            es_host (str | None): Elasticsearch host (overrides config if provided).
            type_of (str): Operation type, e.g. "create" or "update".
        """
        self.type_of = type_of
        self.dry_run = bool(dry_run)
        self.data = read_from_config_file(config_file)
        self.fetcher = FetchSPFromDB(self.data)

        es_cfg = (self.data.get("elasticsearch") or {})
        self.indexer = ElasticSearchIndexer(
            es_host or es_cfg.get("host"),
            "superpopulation",
            es_api_key=es_cfg.get("api_key"),
            es_username=es_cfg.get("username"),
            es_password=es_cfg.get("password"),
            es_cloud_id=es_cfg.get("cloud_id"),
        )

    def load_json_file(self) -> dict[str, Any]:
        """Load index settings and mappings from JSON."""
        with open(json_file, "r") as file:
            data = json.load(file)
        return data

    def create_superpopulation_index(self) -> bool:
        """Create the `superpopulation` index."""
        json_data = self.load_json_file()
        superpopulation = self.indexer.create_index(
            json_data["settings"], json_data["mappings"]
        )
        return superpopulation

    def build_and_index_superpopulation(self):
        """Build and bulk index superpopulation documents."""
        t0 = time.time()
        click.echo(f"[info] Index: superpopulation — mode: {self.type_of} — dry_run: {'yes' if self.dry_run else 'no'}")

        rows = self.fetcher.fetch_information_from_db()
        total_rows = len(rows)
        click.echo(f"[info] Found {total_rows} candidate document(s) from DB")

        click.echo("[info] Preparing bulk actions…")
        actions = []
        for i, row in enumerate(rows, 1):
            elastic_id = row[0]
            super_pop_data = self.fetcher.build_superpopulation_info(row)
            action = self.indexer.index_data(super_pop_data, elastic_id, self.type_of)
            actions.append(action)
            if i % 500 == 0:
                click.echo(f"[info] Prepared {i}/{total_rows} actions…")

        click.echo(f"[info] Prepared {len(actions)} action(s)")
        if not actions:
            click.echo("[info] Nothing to do — exiting")
            return

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
                click.echo("[warn] Update requested but index 'superpopulation' does not exist. No changes made. Run once with --type_of=create.")
                return
            click.echo("[info] Upserting into existing index…")
            self.indexer.bulk_index(actions)
            click.echo(f"[ok] Bulk indexing successful ({len(actions)} docs) in {time.time()-t0:.1f}s")


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
    """CLI entry point to build and (re)index the superpopulation index."""
    superpop_indexer = SuperPopulationIndexer(config_file, es_host, type_of, dry_run=dry_run)
    superpop_indexer.build_and_index_superpopulation()


# ──────────────────────────────────────────────────────────────
# Script entry
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    create_data()