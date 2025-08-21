import elasticsearch
import click
from elasticsearch import Elasticsearch, exceptions
from elasticsearch.helpers import bulk, BulkIndexError
from typing import Any, Dict, List, Iterable


class ElasticSearchIndexer:
    """Configuration for the ElasticSearch Index build"""

    def __init__(self, es_host: str, index_name: str):
        """Initialization of the ElasticSearchIndexer Class

        Args:
            es_host (str): Host of the ElasticSearch
            index_name (str): name of the index
        """
        self.client = Elasticsearch(es_host)
        self.index_name = index_name

    def create_index(self, settings: dict[str, Any], mappings: dict[str, Any]) -> bool:
        """Creates an ElasticSearch Index with the settings and mappings

        Args:
            settings (dict[str, Any]): settings for the index
            mappings (dict[str, Any]): mappings for the index

        Returns:
            bool: True or False
        """
        if self.client.indices.exists(index=self.index_name):
            click.echo(
                f"Index '{self.index_name}' already exists., Change --type_of to update"
            )
            return False
        try:
            self.client.indices.create(
                index=self.index_name, body={"settings": settings, "mappings": mappings}
            )
            click.echo(f"Index '{self.index_name}' created successfully.")
            return True
        except exceptions as e:
            click.echo(f"Failed to create index: {e}")
            return False

    def index_data(
        self, data: dict[str, Any], doc_id: str, action_type: str
    ) -> dict[str, Any]:
        """Creation of the index (required for the action for bulk action)

        Args:
            data (dict): The data to index
            doc_id (str): Document ID
            action_type (str): Action type: create or update

        Returns:
            dict[str, Any]: Bulk indexing action dict
        """
        if action_type == "create":
            return {
                "_op_type": action_type,
                "_index": self.index_name,
                "_id": doc_id,
                "_source": data,
            }
        elif action_type == "update":
            return {
                "_op_type": action_type,
                "_index": self.index_name,
                "_id": doc_id,
                "doc": data,
                "doc_as_upsert": True,
            }
        else:
            raise ValueError(f"Unsupported action_type: {action_type}")

    def bulk_index(self, actions: List[Dict[str, Any]]):
        """
        Perform a bulk indexing operation.

        Args:
            actions (List[Dict[str, Any]]): List of actions to be indexed

        Raises:
            Exception: Raised on any bulk indexing failure
        """
        try:
            bulk(self.client, actions)
        except elasticsearch.BadRequestError as e:
            raise Exception(f"Error during bulk indexing: {str(e)}")
        except BulkIndexError as e:
            click.echo("Bulk indexing failed")
            for error in e.errors:
                click.echo(error)

    def delete_data(self, doc_id: str) -> Dict[str, Any]:
        return {
            "_op_type": "delete",
            "_index": self.index_name,
            "_id": doc_id,
        }
