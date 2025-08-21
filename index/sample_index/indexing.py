import click
import sys
import json
from typing import Any
from index.elasticsearch_indexer import ElasticSearchIndexer
from .fetch_samples_from_db import SampleDetailsFetcher
from index.config_read import read_from_config_file

json_file = "index/sample_index/sample.json"


class SampleIndexer:
    """SampleIndexer Class"""

    def __init__(self, config_file: str, es_host: str, type_of: str):
        """Initializing of the Sample Indexer class

        Args:
            config_file (str): Configuration file
            es_host (str): Elasticsearch host
            type_of (str): Type of whether create or update
        """
        self.config_file = config_file
        self.es_host = es_host
        self.type_of = type_of
        self._data = None
        self._fetcher = None
        self._indexer = None

    @property
    def data(self):
        """Property function for data

        Returns:
            _type_: self.data
        """
        if self._data is None:
            self._data = read_from_config_file(self.config_file)

        return self._data

    @property
    def fetcher(self):
        """Property function of fetcher

        Returns:
            _type_: self.fetcher
        """
        if self._fetcher is None:
            self._fetcher = SampleDetailsFetcher(self.data)
        return self._fetcher

    @property
    def indexer(self):
        """Property function of indexer

        Returns:
            _type_: self.indexer
        """
        if self._indexer is None:
            self._indexer = ElasticSearchIndexer(self.es_host, "sample")
        return self._indexer

    def load_json_file(self) -> dict[str, Any]:
        """Loading Json file to get the settings and the mappings

        Returns:
            dict[str, Any]: json data
        """
        with open(json_file, "r") as file:
            data = json.load(file)

        return data

    def create_sample_index(self) -> bool:
        """Create Sample index

        Returns:
            bool: True or False if index is created
        """
        json_data = self.load_json_file()
        sample = self.indexer.create_index(json_data["settings"], json_data["mappings"])

        return sample

    def generate_actions(self):
        """Generate actions that will be used for bulk index (with batched preloads)."""
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
            yield self.indexer.index_data(samples_data, code, self.type_of)

    def build_and_index_sample_info(self):
        """Build and index sample information

        Returns:
            _type_: Bulk actions
        """
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
    sample_indexer = SampleIndexer(config_file, es_host, type_of)
    sample_indexer.build_and_index_sample_info()


if __name__ == "__main__":
    create_data()
