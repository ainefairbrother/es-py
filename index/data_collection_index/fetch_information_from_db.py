from mysql.connector import connect
from typing import Any
from .utils import create_the_dictionary_structure


class DCDetailsFetcher:
    """DataCollectionDetails Fetcher class"""

    def __init__(self, db_config: dict):
        """Initialization of the DCDetailsFetcher clasd

        Args:
            db_config (dict): DB configuration
        """
        self.host = db_config["host"]
        self.port = db_config["port"]
        self.user = db_config["user"]
        self.password = db_config["password"]
        self.database = db_config["database"]

    def fetch_datacollections(self) -> list[tuple]:
        """Fetch dataCollections from the database

        Returns:
            list[tuple]: List of rows from the database
        """

        select_all_dc_sql = "SELECT * from data_collection"

        db = connect(
            host=self.host,
            port=self.port,
            user=self.user,
            database=self.database,
            password=self.password,
        )

        cursor = db.cursor()
        cursor.execute(select_all_dc_sql)
        data_collection = cursor.fetchall()
        cursor.close()

        return data_collection

    def fetch_samples_count(self, dc_id: int) -> int:
        """Fetching samples count from the database

        Args:
            dc_id (int): Datacollection id

        Returns:
            int: The sample count
        """

        select_samples_count = """ SELECT count(samples.sample_id) AS num_samples
                        FROM (
                        SELECT DISTINCT sf.sample_id
                        FROM sample_file sf, file_data_collection fdc
                        WHERE sf.file_id = fdc.file_id AND fdc.data_collection_id = %s
                    ) AS samples """

        db = connect(
            host=self.host,
            port=self.port,
            user=self.user,
            database=self.database,
            password=self.password,
        )
        cursor = db.cursor()
        cursor.execute(select_samples_count, (dc_id,))
        samples_count = cursor.fetchone()[0]
        cursor.close()
        db.close()

        return samples_count

    def fetch_population_count(self, dc_id: int) -> int:
        """Fetch population count from the database

        Args:
            dc_id (int): Datacollection id

        Returns:
            int: The population count
        """

        select_population_count = """ SELECT count(*) AS num_populations
                                FROM (
                            SELECT DISTINCT dcsp.population_id
                            FROM sample_file sf,
                                file_data_collection fdc,
                                sample s,
                                dc_sample_pop_assign dcsp
                            WHERE dcsp.data_collection_id = fdc.data_collection_id
                            AND dcsp.sample_id = s.sample_id
                            AND s.sample_id = sf.sample_id
                            AND sf.file_id = fdc.file_id
                            AND fdc.data_collection_id = %s
                        ) AS populations """

        db = connect(
            host=self.host,
            port=self.port,
            user=self.user,
            database=self.database,
            password=self.password,
        )
        cursor = db.cursor()
        cursor.execute(select_population_count, (dc_id,))
        population_count = cursor.fetchone()[0]
        cursor.close()
        db.close()

        return population_count

    def fetch_publication_info(self, dc_id: int) -> list[tuple]:
        """Fetches publication from the database for each datacollection id

        Args:
            dc_id (int): Datacollection id

        Returns:
            list[tuple]: List of rows of information from the database
        """

        publication_info_sql = """Select * from publications where data_collection_id=%s and publication is NOT NULL"""

        db = connect(
            host=self.host,
            port=self.port,
            user=self.user,
            database=self.database,
            password=self.password,
        )

        cursor = db.cursor()
        cursor.execute(publication_info_sql, (dc_id,))
        publication_info = cursor.fetchall()
        cursor.close()
        db.close()

        return publication_info

    def fetch_analysis_information(self, dc_id) -> list[tuple]:
        """Fetches Analysis group information from the database

        Args:
            dc_id (_type_): Data collection id

        Returns:
            list[tuple]: List of rows of information from the database
        """
        analysis_info_sql = """SELECT dt.code data_type, ag.description analysis_group
            FROM file f LEFT JOIN data_type dt ON f.data_type_id = dt.data_type_id
            LEFT JOIN analysis_group ag ON f.analysis_group_id = ag.analysis_group_id
            INNER JOIN file_data_collection fdc ON f.file_id=fdc.file_id
            WHERE fdc.data_collection_id= %s AND dt.code IS NOT NULL
            GROUP BY dt.data_type_id, ag.analysis_group_id """

        db = connect(
            host=self.host,
            port=self.port,
            user=self.user,
            database=self.database,
            password=self.password,
        )

        cursor = db.cursor()
        cursor.execute(analysis_info_sql, (dc_id,))
        analysis_info = cursor.fetchall()
        cursor.close()
        db.close()

        return analysis_info

    def populate_the_dictionary_structure(self, row: tuple) -> dict[str, Any]:
        """Populating the dataCollection dictionary

        Args:
            row (tuple): The row containing info from the fetch_datacollections

        Returns:
            dict[str, Any]: Updated dictionary
        """
        dc_data = create_the_dictionary_structure()
        dc_data.update(
            {
                "code": row[1],
                "title": row[2],
                "shortTitle": row[3],
                "displayOrder": row[4],
                "dataReusePolicy": row[5],
                "website": row[7],
                "samples": {"count": self.fetch_samples_count(row[0])},
                "populations": {"count": self.fetch_population_count(row[0])},
            }
        )

        publications = self.fetch_publication_info(row[0])
        for pub in publications:
            dc_data["publications"].append(
                {"displayOrder": pub[2], "name": pub[3], "url": pub[1]}
            )

        for dtype, ag_desc in self.fetch_analysis_information(row[0]):
            if not dtype: # skip empty/None dtype
                continue
            if ag_desc is None: # skip empty analysis_group names
                continue
            dc_data.setdefault(dtype, [])
            if ag_desc not in dc_data[dtype]:
                dc_data[dtype].append(ag_desc)

            dc_data.setdefault("dataTypes", [])
            if dtype not in dc_data["dataTypes"]:
                dc_data["dataTypes"].append(dtype)

        return dc_data
