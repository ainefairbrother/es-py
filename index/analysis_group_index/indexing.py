import click
from typing import Any
import json
from index.elasticsearch_indexer import ElasticSearchIndexer
from .fetch_information_from_db import FetchAGFromDB
from index.config_read import read_from_config_file


json_file = "index/analysis_group_index/analysis_group.json"


class AnalysisGroupIndexer:
    """Analysis group indexer class"""

    def __init__(self, config_file: str, es_host: str, type_of: str):
        """Initiaization of the analysis group indexer class

        Args:
            config_file (str): Configuration file
            es_host (str): ElasticSearch Host
            type_of (str): Type of either create or update
        """

        self.type_of = type_of
        self.data = read_from_config_file(config_file)
        self.fetcher = FetchAGFromDB(self.data)
        self.indexer = ElasticSearchIndexer(es_host, "analysis_group")

    def load_json_file(self) -> dict[str, Any]:
        """Loading Json file to get the settings and the mappings

        Returns:
            dict[str, Any]: json data
        """
        with open(json_file, "r") as file:
            data = json.load(file)

        return data

    def create_analysis_group_index(self) -> bool:
        """Create Analysis group index

        Returns:
            bool: True or False if index is created
        """
        json_data = self.load_json_file()
        analysis_group = self.indexer.create_index(
            json_data["settings"], json_data["mappings"]
        )

        return analysis_group

    def build_and_index_analysisgroup(self):
        """Build and index analysis group"""

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
    ag_indexer = AnalysisGroupIndexer(config_file, es_host, type_of)
    ag_indexer.build_and_index_analysisgroup()


if __name__ == "__main__":
    create_data()
