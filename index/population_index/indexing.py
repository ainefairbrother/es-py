import click
import json
from typing import Any
from index.elasticsearch_indexer import ElasticSearchIndexer
from index.population_index.fetch_information_from_db import PopulationDetailsFetcher
from index.config_read import read_from_config_file

json_file = "index/population_index/populations_mappings.json"


class PopulationIndexer:
    def __init__(self, config_file: str, es_host: str, type_of: str):
        """Initialization of the class

        Args:
            config_file (str): Configuration file
            es_host (str): ElasticSearch Host
            type_of (str): Type of
        """
        self.config_file = config_file
        self.es_host = es_host
        self.type_of = type_of
        self.data = read_from_config_file(config_file)
        self.fetcher = PopulationDetailsFetcher(self.data)
        self.indexer = ElasticSearchIndexer(es_host, "population")

    def load_json_file(self) -> dict[str, Any]:
        """Loading Json file to get the settings and the mappings

        Returns:
            dict[str, Any]: json data
        """
        with open(json_file, "r") as file:
            data = json.load(file)

        return data

    def create_population_index(self) -> bool:
        """Create population index

        Returns:
            bool: True or False if index is created
        """
        json_data = self.load_json_file()
        population = self.indexer.create_index(
            json_data["settings"], json_data["mappings"]
        )

        return population

    def build_and_index_population_info(self):
        """Build and index population info"""
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

            action = self.indexer.index_data(population_data, code, self.type_of)
            actions.append(action)

        if self.type_of == "create":
            if self.create_population_index() is True:
                self.indexer.bulk_index(actions)
                click.echo(f"Bulk indexing successful")
        else:
            self.indexer.bulk_index(actions)
            click.echo(f"Bulk indexing successful")


@click.command()
@click.option("--config_file", "-c", type=click.Path(exists=True), required=True)
@click.option("--es_host", "-es", type=str, required=True)
@click.option("--type_of", "-t", type=str, required=True)
def create_data(config_file: str, es_host: str, type_of: str):
    indexer = PopulationIndexer(config_file, es_host, type_of)
    result = indexer.build_and_index_population_info()


# Enables CLI use
if __name__ == "__main__":
    create_data()


# Enables programmatic use (from main.py)
def run(config_file, es_host, type_of):
    indexer = PopulationIndexer(config_file, es_host, type_of)
    result = indexer.build_and_index_population_info()
    print(result)
