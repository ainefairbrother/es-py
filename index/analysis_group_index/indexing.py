"""Analysis Group indexer.

Provides a CLI and programmatic API to build and (re)index the
`analysis_group` index in Elasticsearch from the IGSR database.

This module:
  * Reads ES settings/mappings from a local JSON file.
  * Fetches analysis groups and transforms rows into ES documents.
  * Creates or updates the ES index via bulk operations.

The script uses Click for the CLI and is safe to import for use from
other modules.
"""

# ──────────────────────────────────────────────────────────────
# Imports
# ──────────────────────────────────────────────────────────────

import click
from typing import Any, Optional
import json
import time
from elasticsearch.helpers import BulkIndexError
from index.elasticsearch_indexer import ElasticSearchIndexer
from .fetch_information_from_db import FetchAGFromDB
from index.config_read import read_from_config_file


# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────

json_file = "index/analysis_group_index/analysis_group.json"


# ──────────────────────────────────────────────────────────────
# Indexer
# ──────────────────────────────────────────────────────────────


class AnalysisGroupIndexer:
    """Indexer for the `analysis_group` index."""

    def __init__(self, config_file: str, es_host: Optional[str], type_of: str, dry_run: bool = False):
        """Initialise the indexer.

        Args:
            config_file (str): Path to the configuration file with DB credentials.
            es_host (str | None): Elasticsearch host (overrides config if provided).
            type_of (str): Operation type, either "create" or "update".
        """
        self.type_of = type_of
        self.dry_run = bool(dry_run)
        self.data = read_from_config_file(config_file)
        self.fetcher = FetchAGFromDB(self.data)

        es_cfg = (self.data.get("elasticsearch") or {})
        self.indexer = ElasticSearchIndexer(
            es_host or es_cfg.get("host"),
            "analysis_group",
            es_api_key=es_cfg.get("api_key"),
            es_username=es_cfg.get("username"),
            es_password=es_cfg.get("password"),
            es_cloud_id=es_cfg.get("cloud_id"),
        )

    def load_json_file(self) -> dict[str, Any]:
        """Load index settings and mappings JSON.

        Returns:
            dict[str, Any]: Parsed JSON with "settings" and "mappings".
        """
        with open(json_file, "r") as file:
            data = json.load(file)
        return data

    def create_analysis_group_index(self) -> bool:
        """Create the Elasticsearch index for analysis groups.

        Returns:
            bool: True if the index was created, otherwise False.
        """
        json_data = self.load_json_file()
        analysis_group = self.indexer.create_index(
            json_data["settings"], json_data["mappings"]
        )
        return analysis_group

    def build_and_index_analysisgroup(self):
        """Build and bulk index analysis group documents."""
        t0 = time.time()
        click.echo(f"[info] Index: analysis_group — mode: {self.type_of} — dry_run: {'yes' if self.dry_run else 'no'}")

        rows = self.fetcher.fetch_information_from_DB()
        total_rows = len(rows)
        click.echo(f"[info] Found {total_rows} candidate document(s) from DB")
        if not rows:
            click.echo("[info] Nothing to do — exiting")
            return

        actions = []
        skipped_no_code = 0

        click.echo("[info] Preparing bulk actions…")
        for i, row in enumerate(rows, 1):
            code = row[1]  # analysis_group code
            if not code:
                skipped_no_code += 1
                continue

            ag_data = self.fetcher.build_ag_info(row)
            actions.append(self.indexer.index_data(ag_data, code, self.type_of))

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
                    click.echo("[warn] Update requested but index 'analysis_group' does not exist. No changes made. Run once with --type_of=create.")
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
    """CLI entry point to build and index analysis_group documents."""
    ag_indexer = AnalysisGroupIndexer(config_file, es_host, type_of, dry_run=dry_run)
    ag_indexer.build_and_index_analysisgroup()


# ──────────────────────────────────────────────────────────────
# Script entry
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    create_data()