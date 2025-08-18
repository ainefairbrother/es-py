import click
import sys
import json
from typing import Any
from index.elasticsearch_indexer import ElasticSearchIndexer
from .fetch_information_from_db import FetchFileFromDB
from index.config_read import read_from_config_file

json_file = "index/file_index/file.json"
class FileIndexer:
    """FileIndexer class"""

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
            self._fetcher = FetchFileFromDB(self.data)
        return self._fetcher

    @property
    def indexer(self):
        """Property function of indexer

        Returns:
            _type_: self.indexer
        """
        if self._indexer is None:
            self._indexer = ElasticSearchIndexer(self.es_host, "file")
        return self._indexer
    
    def load_json_file(self) -> dict[str, Any]:
        """Loading Json file to get the settings and the mappings

        Returns:
            dict[str, Any]: json data
        """
        with open(json_file, "r") as file:
            data = json.load(file)

        return data

    def create_file_index(self) -> bool:
        """Create Sample index

        Returns:
            bool: True or False if index is created
        """
        json_data = self.load_json_file()
        file = self.indexer.create_index(
            json_data["settings"], json_data["mappings"]
        )

        return file


    def generate_actions(self):
        """Generate actions that will be used for bulk index

        Yields:
            _type_: A generator
        """
        files_info = self.fetcher.fetch_file_from_db()
        file_id_info = self.fetcher.fetch_file_id_from_db()
        dc_data, sp_data = self.fetcher.preload_data(file_id_info)
        
        for row in files_info:
            file_id = int(row[0])
            # match legacy ES v1.5 IDs - 9 digits, left padded like 000000057
            padded_id = f"{file_id:09d}"
            files_data = self.fetcher.populate_the_dictionary(row, dc_data, sp_data)
            yield self.indexer.index_data(files_data, padded_id, self.type_of)

    def build_and_index_file_info(self):
        """Bulk index for the file

        Returns:
            _type_: Bullk indexed
        """
        actions = self.generate_actions()
        if self.type_of == "create":
            if self.create_file_index() is True:
                self.indexer.bulk_index(actions)
                click.echo("Bulk indexing successful")
        else:
            self.indexer.bulk_index(actions)
            click.echo("Bulk indexing successful")

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
    """_summary_

    Args:
        config_file (str): _description_
        es_host (str): _description_
        type_of (str): _description_
    """
    file_indexer = FileIndexer(config_file, es_host, type_of)
    file_indexer.build_and_index_file_info()


if __name__ == "__main__":
    create_data()
