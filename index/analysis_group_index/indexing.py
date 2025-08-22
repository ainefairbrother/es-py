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
from typing import Any
import json
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

    def __init__(self, config_file: str, es_host: str, type_of: str):
        """Initialise the indexer.

        Args:
            config_file (str): Path to the configuration file with DB credentials.
            es_host (str): Elasticsearch host (e.g., "http://localhost:9200").
            type_of (str): Operation type, either "create" or "update".
        """
        self.type_of = type_of
        self.data = read_from_config_file(config_file)
        self.fetcher = FetchAGFromDB(self.data)
        self.indexer = ElasticSearchIndexer(es_host, "analysis_group")

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
        actions = []
        analysis_group = self.fetcher.fetch_information_from_DB()
        for row in analysis_group:
            code = row[1]
            ag_data = self.fetcher.build_ag_info(row)
            action = self.indexer.index_data(ag_data, code, self.type_of)
            actions.append(action)

        if self.type_of == "create":
            if self.create_analysis_group_index() is True:
                self.indexer.bulk_index(actions)
                click.echo(f"Bulk indexing successful")
        else:
            self.indexer.bulk_index(actions)
            click.echo(f"Bulk indexing successful")


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
    """CLI entry point to build and index analysis_group documents.

    Args:
        config_file (str): Path to configuration file with DB connection details.
        es_host (str): Elasticsearch host URL.
        type_of (str): Operation type, either "create" or "update".
    """
    ag_indexer = AnalysisGroupIndexer(config_file, es_host, type_of)
    ag_indexer.build_and_index_analysisgroup()


# ──────────────────────────────────────────────────────────────
# Script entry
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    create_data()
