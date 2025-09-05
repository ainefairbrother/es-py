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
from typing import Any
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

    def __init__(self, config_file: str, es_host: str, type_of: str):
        """Initialise the indexer.

        Args:
            config_file (str): Path to the configuration file with DB credentials.
            es_host (str): Elasticsearch host (e.g., "http://localhost:9200").
            type_of (str): Operation type (e.g., "create" or "update").
        """
        self.config_file = config_file
        self.es_host = es_host
        self.type_of = type_of
        self.data = read_from_config_file(config_file)
        self.fetcher = PopulationDetailsFetcher(self.data)
        self.indexer = ElasticSearchIndexer(es_host, "population")

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
        pop_info = self.fetcher.fetch_population()
        pop_ids = self.fetcher.fetch_population_ids()
        actions = []
        dc_map = self.fetcher.fetch_data_collection_details(pop_ids)
        overlap_map = self.fetcher.fetch_overlap_population_details(pop_ids)
        for row in pop_info:
            code = row[5]
            if not code:
                continue

            population_data = self.fetcher.build_population_info(
                row, dc_map, overlap_map
            )

            flat = []
            for dc in population_data.get("dataCollections", []):
                for key in ("variants", "sequence", "alignment"):
                    vals = dc.get(key)
                    if vals:
                        flat.extend(vals)
            population_data["dataCollectionsAnalysisGroups"] = flat

            action = self.indexer.index_data(population_data, code, self.type_of)
            actions.append(action)

        if self.type_of == "create":
            if self.create_population_index() is True:
                self.indexer.bulk_index(actions)
                click.echo("Bulk indexing successful")
        else:
            self.indexer.bulk_index(actions)
            click.echo("Bulk indexing successful")


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────


@click.command()
@click.option("--config_file", "-c", type=click.Path(exists=True), required=True)
@click.option("--es_host", "-es", type=str, required=True)
@click.option("--type_of", "-t", type=str, required=True)
def create_data(config_file: str, es_host: str, type_of: str):
    """CLI entry point to build and index population documents.

    Args:
        config_file (str): Path to configuration file with DB connection details.
        es_host (str): Elasticsearch host URL.
        type_of (str): Operation type, such as "create" or "update".
    """
    indexer = PopulationIndexer(config_file, es_host, type_of)
    result = indexer.build_and_index_population_info()


# ──────────────────────────────────────────────────────────────
# Script entry
# ──────────────────────────────────────────────────────────────

# Enables CLI use
if __name__ == "__main__":
    create_data()


# ──────────────────────────────────────────────────────────────
# Programmatic API
# ──────────────────────────────────────────────────────────────


# Enables programmatic use (from main.py)
def run(config_file, es_host, type_of):
    """Programmatic entry point mirroring the CLI behaviour.

    Args:
        config_file: Path to configuration file with DB connection details.
        es_host: Elasticsearch host URL.
        type_of: Operation type, such as "create" or "update".
    """
    indexer = PopulationIndexer(config_file, es_host, type_of)
    result = indexer.build_and_index_population_info()
    print(result)
