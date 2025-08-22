"""File details fetcher.

Provides DB accessors to retrieve and assemble information needed to build
`file` documents for Elasticsearch. This module encapsulates SQL queries
and the shaping of results into a consistent dictionary structure suitable
for indexing.

All functionality is exposed via the `FetchFileFromDB` class.
"""

# ──────────────────────────────────────────────────────────────
# Imports
# ──────────────────────────────────────────────────────────────

import mysql.connector
from typing import Any
from .utils import create_the_dictionary_structure
from collections import defaultdict


# ──────────────────────────────────────────────────────────────
# Fetcher
# ──────────────────────────────────────────────────────────────


class FetchFileFromDB:
    """Fetch file metadata and related entities from the database."""

    def __init__(self, db_config: dict):
        """Initialise the fetcher.

        Args:
            db_config (dict): Database configuration containing keys:
                "host", "port", "user", "password", "database".
        """
        self.db_config = db_config

    def fetch_files(self) -> list[tuple]:
        """Fetch files eligible for indexing.

        Uses the exact selection criteria supplied: foreign_file OR in_current_tree.

        Returns:
            list[tuple]: Rows containing file metadata joined to data type
            and analysis group for files that should be indexed.
        """
        fetch_files_sql = """
        SELECT f.file_id, f.url, f.md5, dt.code, ag.description
        FROM file f
        LEFT JOIN data_type dt       ON f.data_type_id     = dt.data_type_id
        LEFT JOIN analysis_group ag  ON f.analysis_group_id = ag.analysis_group_id
        WHERE (f.foreign_file IS TRUE OR f.in_current_tree IS TRUE)
        ORDER BY f.file_id
        """

        db = mysql.connector.connect(
            host=self.db_config["host"],
            port=self.db_config["port"],
            user=self.db_config["user"],
            database=self.db_config["database"],
            password=self.db_config["password"],
        )

        cursor = db.cursor()
        cursor.execute(fetch_files_sql)
        files = cursor.fetchall()
        cursor.close()
        db.close()

        return files

    def preload_data(self, file_ids: list[int]) -> tuple[defaultdict, defaultdict]:
        """Preload related data to reduce DB round-trips.

        Args:
            file_ids (list[int]): List of file IDs to preload data for.

        Returns:
            tuple[defaultdict, defaultdict]: Two mappings:
                - dc_map[file_id] -> List[(data_collection_title, reuse_policy)]
                - sp_map[file_id] -> List[(sample_name, population_description)]
        """
        # Avoid SQL "IN ()" when there are no IDs to preload
        if not file_ids:
            return defaultdict(list), defaultdict(list)

        format_strings = ",".join(["%s"] * len(file_ids))

        fetch_datacollections_sql = f"""
        SELECT fdc.file_id, dc.title, dc.reuse_policy from data_collection dc, file_data_collection fdc
        WHERE fdc.data_collection_id=dc.data_collection_id 
        AND fdc.file_id IN ({format_strings})
        ORDER BY dc.reuse_policy_precedence
        """

        db = mysql.connector.connect(
            host=self.db_config["host"],
            port=self.db_config["port"],
            user=self.db_config["user"],
            database=self.db_config["database"],
            password=self.db_config["password"],
        )

        cursor = db.cursor()
        cursor.execute(fetch_datacollections_sql, file_ids)
        dc_map = defaultdict(list)
        for file_id, collection, resuse_policy in cursor.fetchall():
            dc_map[file_id].append((collection, resuse_policy))

        fetch_sample_sql = f"""
        SELECT  distinct file_data_collection.file_id, sample.name, population.description AS pop_description 
        FROM file_data_collection, sample_file, sample, dc_sample_pop_assign, population
        WHERE file_data_collection.file_id IN ({format_strings}) 
        AND sample_file.file_id = file_data_collection.file_id  
        AND sample_file.sample_id = sample.sample_id 
        AND sample.sample_id=dc_sample_pop_assign.sample_id 
        AND file_data_collection.data_collection_id = dc_sample_pop_assign.data_collection_id 
        AND dc_sample_pop_assign.population_id =population.population_id
        """

        cursor.execute(fetch_sample_sql, file_ids)
        sp_map = defaultdict(list)
        for file_id, sample, population in cursor.fetchall():
            sp_map[file_id].append((sample, population))

        cursor.close()
        db.close()
        return dc_map, sp_map

    ## FLAG flipper - not implemented yet
    # def update_elasticsearch_file(self) -> list[tuple]:
    #     """Update the `indexed_in_elasticsearch` column.

    #     Sets `indexed_in_elasticsearch = 1` for files where
    #     `(foreign_file IS TRUE OR in_current_tree IS TRUE)`.

    #     Returns:
    #         list[tuple]: A list of rows from the DB (not used here).
    #     """
    #     update_elasticsearch_sql = """
    #     UPDATE file SET indexed_in_elasticsearch = (foreign_file IS TRUE OR in_current_tree IS TRUE)
    #     """

    #     db = mysql.connector.connect(
    #         host=self.db_config["host"],
    #         port=self.db_config["port"],
    #         user=self.db_config["user"],
    #         database=self.db_config["database"],
    #         password=self.db_config["password"],
    #     )

    #     cursor = db.cursor()
    #     cursor.execute(update_elasticsearch_sql)
    #     db.commit()
    #     cursor.close()
    #     db.close()

    def populate_the_dictionary(
        self, row: tuple, dc_map: defaultdict, sp_map: defaultdict
    ) -> dict[str, Any]:
        """Build the file document structure for indexing.

        Args:
            row (tuple): Row returned by the file fetcher methods.
            dc_map (defaultdict): Mapping of file_id to data-collection tuples.
            sp_map (defaultdict): Mapping of file_id to (sample, population) tuples.

        Returns:
            dict[str, Any]: A fully-populated file document ready for indexing.
        """
        file_id = row[0]
        file_dict = create_the_dictionary_structure()

        for dc in dc_map.get(file_id, []):
            file_dict["dataCollections"].append(dc[0])
            file_dict["dataReusePolicy"] = dc[1]

        for s_pop in sp_map.get(file_id, []):
            file_dict["samples"].append(s_pop[0])
            file_dict["populations"].append(s_pop[1])

        # get unique populations
        file_dict["populations"] = list(set(file_dict["populations"]))

        file_dict.update(
            {
                "dataType": row[3],
                "analysisGroup": row[4],
                "url": row[1],
                "md5": row[2],
            }
        )

        return file_dict
