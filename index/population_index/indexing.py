"""Population indexer.

Provides a CLI and programmatic API to build and (re)index the `population`
index in Elasticsearch from the IGSR database.

This module:
  * Reads ES settings/mappings from a local JSON file.
  * Fetches population data and transforms rows into ES documents.
  * Creates or updates the ES index via bulk operations.

The script uses Click for the CLI and is safe to import for use from
other modules (see `run()`).
"""

# ──────────────────────────────────────────────────────────────
# Imports
# ──────────────────────────────────────────────────────────────

import click
import json
import time
from elasticsearch.helpers import BulkIndexError
from typing import Any, Optional
from index.elasticsearch_indexer import ElasticSearchIndexer
from index.population_index.fetch_information_from_db import PopulationDetailsFetcher
from index.config_read import read_from_config_file


# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────

json_file = "index/population_index/populations_mappings.json"


# ──────────────────────────────────────────────────────────────
# Indexer
# ──────────────────────────────────────────────────────────────


class PopulationIndexer:
    """Indexer for the `population` index."""

    def __init__(self, config_file: str, es_host: Optional[str], type_of: str):
        """Initialise the indexer.

        Args:
            config_file (str): Path to the configuration file with DB credentials.
            es_host (str | None): Elasticsearch host (overrides config if provided).
            type_of (str): Operation type (e.g., "create" or "update").
        """
        self.config_file = config_file
        self.es_host = es_host
        self.type_of = type_of

        # DB + site + elasticsearch all come from this helper
        self.data = read_from_config_file(config_file)

        self.fetcher = PopulationDetailsFetcher(self.data)

        # Build ES client from config, with CLI override for host if provided
        es_cfg = (self.data.get("elasticsearch") or {})
        self.indexer = ElasticSearchIndexer(
            self.es_host or es_cfg.get("host"),
            "population",
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

    def create_population_index(self) -> bool:
        """Create the Elasticsearch index for populations.

        Returns:
            bool: True if the index was created, otherwise False.
        """
        json_data = self.load_json_file()
        population = self.indexer.create_index(
            json_data["settings"], json_data["mappings"]
        )
        return population

    def build_and_index_population_info(self):
        """Bulk index population documents."""
        t0 = time.time()
        click.echo(f"[info] Index: population — mode: {self.type_of}")

        pop_info = self.fetcher.fetch_population()
        total_rows = len(pop_info)
        click.echo(f"[info] Found {total_rows} candidate document(s) from DB")
        if not pop_info:
            click.echo("[info] Nothing to do — exiting")
            return

        pop_ids = self.fetcher.fetch_population_ids()
        dc_map = self.fetcher.fetch_data_collection_details(pop_ids)
        overlap_map = self.fetcher.fetch_overlap_population_details(pop_ids)

        click.echo("[info] Preparing bulk actions…")
        actions = []
        skipped_no_code = 0

        for i, row in enumerate(pop_info, 1):
            code = row[5]
            if not code:
                skipped_no_code += 1
                continue

            population_data = self.fetcher.build_population_info(row, dc_map, overlap_map)

            # Flatten analysis group buckets into a single helper array, as before
            flat = []
            for dc in population_data.get("dataCollections", []):
                for key in ("variants", "sequence", "alignment"):
                    vals = dc.get(key)
                    if vals:
                        flat.extend(vals)
            population_data["dataCollectionsAnalysisGroups"] = flat

            actions.append(self.indexer.index_data(population_data, code, self.type_of))

            if i % 500 == 0:
                click.echo(f"[info] Prepared {i}/{total_rows} actions…")

        click.echo(f"[info] Prepared {len(actions)} action(s); skipped {skipped_no_code} row(s) without a population code")

        if not actions:
            click.echo("[warn] No actions to send — exiting")
            return

        try:
            if self.type_of == "create":
                if self.create_population_index() is True:
                    self.indexer.bulk_index(actions)
                    click.echo(f"[ok] Bulk indexing successful ({len(actions)} docs) in {time.time()-t0:.1f}s")
                else:
                    # Index already exists; still proceed to bulk update
                    self.indexer.bulk_index(actions)
                    click.echo(f"[ok] Index existed; bulk indexing successful ({len(actions)} docs) in {time.time()-t0:.1f}s")
            else:
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
@click.option("--config_file", "-c", type=click.Path(exists=True), required=True)
@click.option("--es_host", "-es", type=str, required=False, help="Elasticsearch host (overrides config)")
@click.option("--type_of", "-t", type=str, required=True)
def create_data(config_file: str, es_host: Optional[str], type_of: str):
    """CLI entry point to build and index population documents."""
    indexer = PopulationIndexer(config_file, es_host, type_of)
    indexer.build_and_index_population_info()


# ──────────────────────────────────────────────────────────────
# Script entry
# ──────────────────────────────────────────────────────────────

# Enables CLI use
if __name__ == "__main__":
    create_data()


# ──────────────────────────────────────────────────────────────
# Programmatic API
# ──────────────────────────────────────────────────────────────


# Enables programmatic use
def run(config_file, es_host, type_of):
    """Programmatic entry point mirroring the CLI behaviour."""
    indexer = PopulationIndexer(config_file, es_host, type_of)
    result = indexer.build_and_index_population_info()
    print(result)