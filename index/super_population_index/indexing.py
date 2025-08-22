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
from typing import Any
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

    def __init__(self, config_file: str, es_host: str, type_of: str):
        """Initialise the indexer.

        Args:
            config_file (str): Path to configuration file.
            es_host (str): Elasticsearch host.
            type_of (str): Operation type, e.g. "create" or "update".
        """
        self.type_of = type_of
        self.data = read_from_config_file(config_file)
        self.fetcher = FetchSPFromDB(self.data)
        self.indexer = ElasticSearchIndexer(es_host, "superpopulation")

    def load_json_file(self) -> dict[str, Any]:
        """Load index settings and mappings from JSON.

        Returns:
            dict[str, Any]: Parsed JSON with "settings" and "mappings".
        """
        with open(json_file, "r") as file:
            data = json.load(file)

        return data

    def create_superpopulation_index(self) -> bool:
        """Create the `superpopulation` index.

        Returns:
            bool: True if the index was created successfully, otherwise False.
        """
        json_data = self.load_json_file()
        superpopulation = self.indexer.create_index(
            json_data["settings"], json_data["mappings"]
        )

        return superpopulation

    def build_and_index_superpopulation(self):
        """Build and bulk index superpopulation documents."""
        actions = []
        superpopulation = self.fetcher.fetch_information_from_db()
        for row in superpopulation:
            elastic_id = row[0]
            super_pop_data = self.fetcher.build_superpopulation_info(row)
            action = self.indexer.index_data(super_pop_data, elastic_id, self.type_of)
            actions.append(action)

        if self.type_of == "create":
            if self.create_superpopulation_index() is True:
                self.indexer.bulk_index(actions)
                click.echo("Bulk indexing successful")
        else:
            self.indexer.bulk_index(actions)
            click.echo("Bulk indexing successful")


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
@click.option("--es_host", "-es", type=str, help="ElasticSearch host", required=True)
@click.option(
    "--type_of", "-t", type=str, help="Update or create an index", required=True
)
def create_data(config_file: str, es_host: str, type_of: str):
    """CLI entry point to build and (re)index the superpopulation index.

    Args:
        config_file (str): Path to configuration file with DB credentials.
        es_host (str): Elasticsearch host.
        type_of (str): Operation type, e.g. "create" or "update".
    """
    superpop_indexer = SuperPopulationIndexer(config_file, es_host, type_of)
    superpop_indexer.build_and_index_superpopulation()


# ──────────────────────────────────────────────────────────────
# Script entry
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    create_data()
