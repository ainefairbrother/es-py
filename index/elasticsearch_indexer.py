from __future__ import annotations
import os
from typing import Any, Dict, List, Optional
import elasticsearch
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk, BulkIndexError

def make_es(
    host: Optional[str] = None,
    *,
    api_key: Optional[str] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    cloud_id: Optional[str] = None,
    timeout: int = 30,
) -> Elasticsearch:
    host     = host     or os.getenv("ES_HOST", "http://localhost:9200")
    api_key  = api_key  or os.getenv("ES_API_KEY")
    username = username or os.getenv("ES_USERNAME")
    password = password or os.getenv("ES_PASSWORD")
    cloud_id = cloud_id or os.getenv("ES_CLOUD_ID")

    kwargs = dict(retry_on_timeout=True, max_retries=3, request_timeout=timeout)

    if cloud_id:
        if api_key:
            return Elasticsearch(cloud_id=cloud_id, api_key=api_key, **kwargs)
        if username and password:
            return Elasticsearch(cloud_id=cloud_id, basic_auth=(username, password), **kwargs)
        raise RuntimeError("ES_CLOUD_ID set but no ES_API_KEY or ES_USERNAME/ES_PASSWORD")

    if api_key:
        return Elasticsearch(host, api_key=api_key, **kwargs)
    if username and password:
        return Elasticsearch(host, basic_auth=(username, password), **kwargs)
    return Elasticsearch(host, **kwargs)


class ElasticSearchIndexer:
    """Configuration for the ElasticSearch Index build"""

    def __init__(
        self,
        es_host: Optional[str],
        index_name: str,
        *,
        es_api_key: Optional[str] = None,
        es_username: Optional[str] = None,
        es_password: Optional[str] = None,
        es_cloud_id: Optional[str] = None,
        timeout: int = 30,
    ):
        self.client = make_es(
            host=es_host,
            api_key=es_api_key,
            username=es_username,
            password=es_password,
            cloud_id=es_cloud_id,
            timeout=timeout,
        )
        self.index_name = index_name

    def create_index(self, settings: dict[str, Any], mappings: dict[str, Any]) -> bool:
        try:
            if self.client.indices.exists(index=self.index_name):
                print(f"Index '{self.index_name}' already exists. Change --type_of to update.")
                return False
            self.client.indices.create(
                index=self.index_name, body={"settings": settings, "mappings": mappings}
            )
            return True
        except elasticsearch.ApiError as e:
            return False

    def index_data(self, data: dict[str, Any], doc_id: str, action_type: str) -> dict[str, Any]:
        if action_type == "create":
            return {"_op_type": "create", "_index": self.index_name, "_id": doc_id, "_source": data}
        if action_type == "update":
            return {"_op_type": "update", "_index": self.index_name, "_id": doc_id, "doc": data, "doc_as_upsert": True}
        raise ValueError(f"Unsupported action_type: {action_type}")

    def bulk_index(self, actions: List[Dict[str, Any]]) -> None:
        try:
            bulk(self.client, actions, raise_on_error=True)
        except elasticsearch.BadRequestError as e:
            raise Exception(f"Error during bulk indexing: {str(e)}")
        except BulkIndexError as e:
            for err in e.errors:
                print(err)
            raise
        except elasticsearch.ApiError as e:
            raise Exception(f"Bulk request failed: {e}") from e

    def delete_data(self, doc_id: str) -> Dict[str, Any]:
        return {"_op_type": "delete", "_index": self.index_name, "_id": doc_id}
    
    def delete_index(self) -> None:
        # safe delete; ignore missing
        try:
            self.client.indices.delete(index=self.index_name, ignore_unavailable=True)
        except Exception:
            pass

    def ensure_fresh_index(self, settings: dict, mappings: dict) -> None:
        # drop then (re)create
        self.delete_index()
        self.create_index(settings, mappings)

    def index_exists(self) -> bool:
        try:
            return bool(self.client.indices.exists(index=self.index_name))
        except Exception:
            return False

    def refresh_index(self) -> None:
        try:
            self.client.indices.refresh(index=self.index_name)
        except Exception:
            pass