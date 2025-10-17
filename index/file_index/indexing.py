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
            es_host (str | None): Elasticsearch host (e.g., "http://localhost:9200"). Optional—overrides config.
            type_of (str): Operation type, either "create" or "update".
        """
        self.config_file = config_file
        self.es_host = es_host
        self.type_of = type_of
        self._data = None
        self._fetcher = None
        self._indexer = None
        self._es_cfg = None

    @property
    def data(self):
        """Lazily-loaded configuration data.

        Returns:
            Any: Parsed configuration data loaded from `config_file`.
        """
        if self._data is None:
            self._data = read_from_config_file(self.config_file)
        return self._data

    @property
    def fetcher(self):
        """Lazily-built DB fetcher.

        Returns:
            FetchFileFromDB: Instance used to read file-related rows.
        """
        if self._fetcher is None:
            self._fetcher = FetchFileFromDB(self.data)
        return self._fetcher

    @property
    def indexer(self):
        """Lazily-built Elasticsearch indexer.

        Returns:
            ElasticSearchIndexer: Wrapper used for index operations.
        """
        if self._indexer is None:
            if self._es_cfg is None:
                self._es_cfg = self.data.get("elasticsearch", {}) if isinstance(self.data, dict) else {}
            self._indexer = ElasticSearchIndexer(
                self.es_host or self._es_cfg.get("host"),
                "file",
                es_api_key=self._es_cfg.get("api_key"),
                es_username=self._es_cfg.get("username"),
                es_password=self._es_cfg.get("password"),
                es_cloud_id=self._es_cfg.get("cloud_id"),
            )
        return self._indexer

    def load_json_file(self) -> dict[str, Any]:
        """Load index settings and mappings from JSON.

        Returns:
            dict[str, Any]: Parsed JSON with "settings" and "mappings".
        """
        with open(json_file, "r") as file:
            data = json.load(file)
        return data

    def create_file_index(self) -> bool:
        """Create the `file` index.

        Returns:
            bool: True if the index was created successfully, otherwise False.
        """
        json_data = self.load_json_file()
        return self.indexer.create_index(json_data["settings"], json_data["mappings"])

    def generate_actions(self, rows):
        """Generate bulk actions for indexing.

        Yields:
            Any: Actions suitable for `Elasticsearch.helpers.bulk`.
        """
        file_ids = [int(r[0]) for r in rows]
        dc_data, sp_data = self.fetcher.preload_data(file_ids)

        for row in rows:
            padded_id = (
                f"{int(row[0]):09d}"  # match legacy ES v1.5 IDs (9-digit, zero-padded)
            )
            files_data = self.fetcher.populate_the_dictionary(row, dc_data, sp_data)
            yield self.indexer.index_data(files_data, padded_id, self.type_of)

    def build_and_index_file_info(self):
        """Build and bulk-index all eligible files.

        Fetches rows from the database, converts them into ES actions, and
        performs a bulk index. On 'create', the index is created beforehand.

        Raises:
            BulkIndexError: If the bulk indexing operation fails.
        """
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
                    # Index already exists or was not created; still attempt bulk
                    self.indexer.bulk_index(actions)
                    click.echo("Index existed; bulk indexing successful")
            else:
                self.indexer.bulk_index(actions)
                click.echo("Bulk indexing successful")
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
    """CLI entry point to build and index file documents.

    Args:
        config_file (str): Path to configuration file with DB connection details.
        es_host (str | None): Elasticsearch host URL (overrides config).
        type_of (str): Operation type, either "create" or "update".
    """
    file_indexer = FileIndexer(config_file, es_host, type_of)
    file_indexer.build_and_index_file_info()


# ──────────────────────────────────────────────────────────────
# Script entry
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    create_data()