import click
import json
from typing import Any
from index.elasticsearch_indexer import ElasticSearchIndexer
from .fetch_information_from_db import FetchSPFromDB
from index.config_read import read_from_config_file

json_file = "index/super_population_index/superpopulations_mappings.json"


class SuperPopulationIndexer:
    """Class for the Superpopulation Indexer"""

    def __init__(self, config_file: str, es_host: str, type_of: str):
        """Initializes the Superpopulation Indexer class

        Args:
            config_file (str): Configuration file
            es_host (str): ElasticSearch Host
            type_of (str): _description_
        """

        self.type_of = type_of
        self.data = read_from_config_file(config_file)
        self.fetcher = FetchSPFromDB(self.data)
        self.indexer = ElasticSearchIndexer(es_host, "superpopulation")

    def load_json_file(self) -> dict[str, Any]:
        """Loading Json file to get the settings and the mappings

        Returns:
            dict[str, Any]: json data
        """
        with open(json_file, "r") as file:
            data = json.load(file)

        return data

    def create_superpopulation_index(self) -> bool:
        """Create Superpopulation index

        Returns:
            bool: True or False if index is created
        """

        json_data = self.load_json_file()
        superpopulation = self.indexer.create_index(
            json_data["settings"], json_data["mappings"]
        )

        return superpopulation

    def build_and_index_superpopulation(self):
        """Builds and indexes the superpopulation index"""
        actions = []
        superpopulation = self.fetcher.fetch_information_from_db()
        for row in superpopulation:
            code = row[0]
            super_pop_data = self.fetcher.build_superpopulation_info(row)
            action = self.indexer.index_data(super_pop_data, code, self.type_of)
            actions.append(action)

        if self.type_of == "create":
            if self.create_superpopulation_index() is True:
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
    superpop_indexer = SuperPopulationIndexer(config_file, es_host, type_of)
    superpop_indexer.build_and_index_superpopulation()


if __name__ == "__main__":
    create_data()
