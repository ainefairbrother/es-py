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

    def __init__(self, config_file: str, es_host: Optional[str], type_of: str):
        """Initialise the indexer.

        Args:
            config_file: Path to the YAML/JSON configuration file.
            es_host: Elasticsearch host to connect to (optional—overrides config).
            type_of: Operation mode, either 'create' or 'update'.
        """
        self.type_of = type_of
        self.data = read_from_config_file(config_file)
        self.fetcher = DCDetailsFetcher(self.data)

        # Read ES credentials from config; CLI --es_host overrides config host if provided
        es_cfg = self.data.get("elasticsearch", {}) if isinstance(self.data, dict) else {}
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
        actions = []
        data_collection = self.fetcher.fetch_datacollections()
        for row in data_collection:
            code = row[1]
            dc_data = self.fetcher.populate_the_dictionary_structure(row)
            action = self.indexer.index_data(dc_data, code, self.type_of)
            actions.append(action)

        try:
            if self.type_of == "create":
                if self.create_data_collections_index() is True:
                    self.indexer.bulk_index(actions)
                    click.echo(f"Bulk indexing successful")
            else:
                self.indexer.bulk_index(actions)
                click.echo(f"Bulk indexing successful")
        except BulkIndexError as e:
            click.echo("Bulk indexing failed")
            for error in e.errors:
                click.echo(error)


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
@click.option("--es_host", "-es", type=str, help="ElasticSearch host", required=False)
@click.option(
    "--type_of", "-t", type=str, help="Update or create an index", required=True
)
def create_data(config_file: str, es_host: Optional[str], type_of: str):
    """Create or update the `data_collections` index via CLI.

    Args:
        config_file: Path to the configuration file for DB/ES access.
        es_host: Elasticsearch host (overrides config).
        type_of: Either 'create' for a fresh index or 'update' to reindex docs.
    """
    dc_indexer = DataCollectionsIndexer(config_file, es_host, type_of)
    dc_indexer.build_and_index_datacollections()


if __name__ == "__main__":
    create_data()


# ──────────────────────────────────────────────────────────────
# Programmatic API
# ──────────────────────────────────────────────────────────────


def run(config_file, es_host, type_of):
    """Programmatic entry point for indexing.

    This mirrors the CLI behaviour, allowing other modules to invoke
    index creation or updates without spawning a subprocess.

    Args:
        config_file: Path to the configuration file.
        es_host: Elasticsearch host.
        type_of: 'create' or 'update'.
    """
    indexer = DataCollectionsIndexer(config_file, es_host, type_of)
    result = indexer.build_and_index_datacollections()