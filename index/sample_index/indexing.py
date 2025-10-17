"""Sample indexer.

Provides a CLI and programmatic API to build and (re)index the `sample`
index in Elasticsearch from the IGSR database.

This module:
  * Reads ES settings/mappings from a local JSON file.
  * Fetches sample data and transforms rows into ES documents.
  * Creates or updates the ES index via bulk operations, with batched
    preload queries to avoid N+1 database access patterns.

The script uses Click for the CLI and is safe to import for use from
other modules (see `create_data()`).
"""

# ──────────────────────────────────────────────────────────────
# Imports
# ──────────────────────────────────────────────────────────────

import click
import json
from typing import Any, Optional
from index.elasticsearch_indexer import ElasticSearchIndexer
from .fetch_information_from_db import SampleDetailsFetcher
from index.config_read import read_from_config_file


# ──────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────

json_file = "index/sample_index/sample.json"


# ──────────────────────────────────────────────────────────────
# Indexer
# ──────────────────────────────────────────────────────────────


class SampleIndexer:
    """Indexer for the `sample` index."""

    def __init__(self, config_file: str, es_host: Optional[str], type_of: str):
        """Initialise the Sample indexer.

        Args:
            config_file (str): Path to configuration file with DB credentials.
            es_host (str | None): Elasticsearch host (overrides config if provided).
            type_of (str): Operation type (e.g., "create" or "update").
        """
        self.config_file = config_file
        self.es_host = es_host
        self.type_of = type_of
        self._data = None
        self._fetcher = None
        self._indexer = None

    @property
    def data(self):
        """Lazy-read configuration data."""
        if self._data is None:
            self._data = read_from_config_file(self.config_file)
        return self._data

    @property
    def fetcher(self):
        """Lazy-initialise and return the DB fetcher."""
        if self._fetcher is None:
            self._fetcher = SampleDetailsFetcher(self.data)
        return self._fetcher

    @property
    def indexer(self):
        """Lazy-initialise and return the Elasticsearch indexer."""
        if self._indexer is None:
            es_cfg = (self.data.get("elasticsearch") or {})
            self._indexer = ElasticSearchIndexer(
                self.es_host or es_cfg.get("host"),
                "sample",
                es_api_key=es_cfg.get("api_key"),
                es_username=es_cfg.get("username"),
                es_password=es_cfg.get("password"),
                es_cloud_id=es_cfg.get("cloud_id"),
            )
        return self._indexer

    def load_json_file(self) -> dict[str, Any]:
        """Load index settings and mappings JSON."""
        with open(json_file, "r") as file:
            data = json.load(file)
        return data

    def create_sample_index(self) -> bool:
        """Create the `sample` index in Elasticsearch."""
        json_data = self.load_json_file()
        sample = self.indexer.create_index(json_data["settings"], json_data["mappings"])
        return sample

    def generate_actions(self):
        """Generate bulk indexing actions with batched preloads."""
        samples_info = self.fetcher.fetch_samples()
        sample_ids = [int(r[0]) for r in samples_info]  # sample_id

        # preload all dependent data once to avoid N+1 queries
        sources_map = self.fetcher.preload_sources(sample_ids)
        pops_map = self.fetcher.preload_populations(sample_ids)
        dcs_map = self.fetcher.preload_datacollections(sample_ids)
        rels_map = self.fetcher.preload_relationships(sample_ids)
        syns_map = self.fetcher.preload_synonyms(sample_ids)

        for row in samples_info:
            code = row[1]
            samples_data = self.fetcher.build_the_dictionary_structure(
                row,
                sources_map=sources_map,
                populations_map=pops_map,
                dcs_map=dcs_map,
                rels_map=rels_map,
                syns_map=syns_map,
            )

            flat = []
            for dc in samples_data.get("dataCollections", []):
                for key in ("variants", "sequence", "alignment"):
                    vals = dc.get(key)
                    if vals:
                        flat.extend(vals)
            samples_data["dataCollectionsAnalysisGroups"] = flat

            yield self.indexer.index_data(samples_data, code, self.type_of)

    def build_and_index_sample_info(self):
        """Bulk index sample documents."""
        actions = self.generate_actions()
        try:
            if self.type_of == "create":
                if self.create_sample_index() is True:
                    self.indexer.bulk_index(actions)
                    click.echo("Bulk indexing successful")
            else:
                self.indexer.bulk_index(actions)
                click.echo("Bulk indexing successful")
        finally:
            # Ensure DB connection is closed even if bulk indexing raises
            try:
                self.fetcher.close()
            except Exception:
                pass


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
def create_data(config_file: str, es_host: Optional[str], type_of: str):
    """CLI entry point to build and (re)index the `sample` index."""
    sample_indexer = SampleIndexer(config_file, es_host, type_of)
    sample_indexer.build_and_index_sample_info()


# ──────────────────────────────────────────────────────────────
# Script entry
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    create_data()