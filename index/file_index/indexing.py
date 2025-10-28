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

    def __init__(self, config_file: str, es_host: Optional[str], type_of: str):
        """Initialise the indexer.

        Args:
            config_file (str): Path to the configuration file with DB credentials.
            es_host (str | None): Elasticsearch host (overrides config if provided).
            type_of (str): Operation type, either "create" or "update".
        """
        self.config_file = config_file
        self.es_host = es_host
        self.type_of = type_of
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
        rows = self.fetcher.fetch_files()
        if not rows:
            click.echo("No file documents eligible for indexing — nothing to do.")
            return

        click.echo(f"Preparing {len(rows)} file document(s) to index...")
        actions = list(self.generate_actions(rows))

        try:
            if self.type_of == "create":
                if self.create_file_index() is True:
                    self.indexer.bulk_index(actions)
                    click.echo("Bulk indexing successful")
                else:
                    self.indexer.bulk_index(actions)
                    click.echo("Index existed; bulk indexing successful")
            else:
                self.indexer.bulk_index(actions)
                click.echo("Bulk indexing successful")

            # keep indexed_in_elasticsearch db column in sync with ES
            self.fetcher.update_elasticsearch_file()

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
@click.option("--es_host", "-es", type=str, help="Elasticsearch host (overrides config)", required=False)
@click.option(
    "--type_of", "-t", type=str, help="Update or create an index", required=True
)
def create_data(config_file: str, es_host: Optional[str], type_of: str):
    """CLI entry point to build and index file documents."""
    file_indexer = FileIndexer(config_file, es_host, type_of)
    file_indexer.build_and_index_file_info()


# ──────────────────────────────────────────────────────────────
# Script entry
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    create_data()