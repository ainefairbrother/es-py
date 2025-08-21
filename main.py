import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="ElasticSearch Indexing CLI")
    parser.add_argument(
        "index_type",
        choices=[
            "population_index",
            "sample_index",
            "file_index",
            "data_collection_index",
            "super_population_index",
            "analysis_group_index",
        ],
        help="Type of indexer to run",
    )

    # These will be passed to the underlying module
    parser.add_argument("--config_file", required=True, help="Path to config.ini")
    parser.add_argument("--es_host", required=True, help="Elasticsearch host URL")
    parser.add_argument(
        "--type_of",
        choices=["update", "create"],
        default="update",
        help="Indexing operation type",
    )

    args = parser.parse_args()

    # Mapping index types to module paths
    module_map = {
        "population_index": "index.population_index.indexing",
        "sample_index": "index.sample_index.indexing",
        "file_index": "index.file_index.indexing",
        "data_collection_index": "index.data_collection_index.indexing",
        "super_population_index": "index.super_population_index.indexing",
        "analysis_group_index": "index.analysis_group_index.indexing",
    }

    # Add the current directory to sys.path so that `index.` can be resolved
    sys.path.insert(0, ".")

    # Import and run the corresponding module
    module_path = module_map[args.index_type]
    module = __import__(module_path, fromlist=["run"])

    # Convention: each module should expose a `run()` function
    module.run(args.config_file, args.es_host, args.type_of)


if __name__ == "__main__":
    main()
