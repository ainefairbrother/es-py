from mysql.connector import connect
from typing import Any
from index.sample_index.utils import create_the_dictionary_structure


class SampleDetailsFetcher:
    def __init__(self, db_config: dict):
        """Initialization of the SampleDetailsFetcher class

        Args:
            db_config (dict): A dictionary containing the configuration data
        """

        self.db_config = db_config
        self.samples_dict = create_the_dictionary_structure()

    def fetch_samples(self) -> list[tuple]:
        """Fetch samples from the database

        Returns:
            list[tuple]: List of tuples info from the DB
        """

        select_samples_sql = (
            """SELECT s.sample_id, s.name, s.biosample_id, s.sex from sample s"""
        )

        db = connect(
            host=self.db_config["host"],
            port=self.db_config["port"],
            database=self.db_config["database"],
            user=self.db_config["user"],
            password=self.db_config["password"],
        )

        cursor = db.cursor()
        cursor.execute(select_samples_sql)
        samples = cursor.fetchall()
        cursor.close()
        db.close()

        return samples

    def fetch_source_samples(self, sample_id: int) -> list[tuple]:
        """Fetches source sample from the database

        Args:
            sample_id (id): sample id from the database used to fetch the info from the sample

        Returns:
            list[tuple]: Rows of information from the DB
        """

        select_source_sample_sql = """SELECT s_source.sample_source_id, s_source.name, s_source.description, s_source.url from sample s, 
                                        sample_source s_source where s.sample_source_id=s_source.sample_source_id and s.sample_id = %s"""

        db = connect(
            host=self.db_config["host"],
            port=self.db_config["port"],
            database=self.db_config["database"],
            user=self.db_config["user"],
            password=self.db_config["password"],
        )

        cursor = db.cursor()
        cursor.execute(select_source_sample_sql, (sample_id,))
        source = cursor.fetchall()
        cursor.close()
        db.close()

        return source

    def fetch_population_samples(self, sample_id: int) -> list[tuple]:
        """Fetch population info for the samples from the DB

        Args:
            sample_id (int): sample id from the database used to fetch the info from the sample

        Returns:
            list[tuple]: Info from the DB
        """

        select_population_sample_sql = """SELECT DISTINCT population.population_id, population.code, population.name, population.description, population.latitude, 
                                            population.longitude, population.elastic_id, population.superpopulation_id, superpopulation.code, superpopulation.name, superpopulation.display_colour, 
                                            superpopulation.display_order from dc_sample_pop_assign, population, superpopulation where dc_sample_pop_assign.sample_id = %s
                                            and dc_sample_pop_assign.population_id =population.population_id and population.superpopulation_id =superpopulation.superpopulation_id"""

        db = connect(
            host=self.db_config["host"],
            port=self.db_config["port"],
            database=self.db_config["database"],
            user=self.db_config["user"],
            password=self.db_config["password"],
        )

        cursor = db.cursor()
        cursor.execute(select_population_sample_sql, (sample_id,))
        population = cursor.fetchall()
        cursor.close()
        db.close()

        return population

    def fetch_dataCollections_samples(self, sample_id: int) -> list[tuple]:
        """Fetch dataCollections info for the samples from the DB

        Args:
            sample_id (int): sample id from the database used to fetch the info from the sample

        Returns:
            list[tuple]: Info from the DB
        """

        select_datacollection_sample_sql = """SELECT dt.code, ag.description, dc.title, dc.data_collection_id, dc.reuse_policy
                                            FROM file f LEFT JOIN data_type dt ON f.data_type_id = dt.data_type_id
                                            LEFT JOIN analysis_group ag ON f.analysis_group_id = ag.analysis_group_id
                                            INNER JOIN sample_file sf ON sf.file_id=f.file_id
                                            INNER JOIN file_data_collection fdc ON f.file_id=fdc.file_id
                                            INNER JOIN data_collection dc ON fdc.data_collection_id=dc.data_collection_id
                                            WHERE sf.sample_id=%s GROUP BY dt.data_type_id, ag.analysis_group_id, dc.data_collection_id"""

        db = connect(
            host=self.db_config["host"],
            port=self.db_config["port"],
            database=self.db_config["database"],
            user=self.db_config["user"],
            password=self.db_config["password"],
        )

        cursor = db.cursor()
        cursor.execute(select_datacollection_sample_sql, (sample_id,))
        datacollection = cursor.fetchall()
        cursor.close()
        db.close()

        return datacollection

    def fetch_relationship_samples(self, sample_id: int) -> list[tuple]:
        """Fetch relationship samples from the database. This function is not being used yet

        Args:
            sample_id (int): sample id information

        Returns:
            list[tuple]: Info from the DB
        """

        select_relationship_sample_sql = """SELECT s.name, sr.type FROM sample s, sample_relationship sr WHERE sr.relation_sample_id=s.sample_id AND sr.subject_sample_id=%s"""

        db = connect(
            host=self.db_config["host"],
            port=self.db_config["port"],
            database=self.db_config["database"],
            user=self.db_config["user"],
            password=self.db_config["password"],
        )

        cursor = db.cursor()
        cursor.execute(select_relationship_sample_sql, (sample_id,))
        sample_relationship = cursor.fetchall()
        cursor.close()
        db.close()

        return sample_relationship

    def fetch_sample_synonyms_sql(self, sample_id: int) -> list[tuple]:
        """Fetch sample synonyms. This function is not being used yet

        Args:
            sample_id (int): sample id information

        Returns:
            list[tuple]: Info from the DB
        """

        select_sample_synonyms_sql = (
            """SELECT synonym from sample_synonym where sample_id = %s"""
        )

        db = connect(
            host=self.db_config["host"],
            port=self.db_config["port"],
            database=self.db_config["database"],
            user=self.db_config["user"],
            password=self.db_config["password"],
        )

        cursor = db.cursor()
        cursor.execute(select_sample_synonyms_sql, (sample_id,))
        sample_synonyms = cursor.fetchall()
        cursor.close()
        db.close()

        return sample_synonyms

    def populate_source_samples(self, sample_id: int) -> list:
        """Populating source samples 

        Args:
            sample_id (int): sample id information

        Returns:
            list: A list of dictionary containing source information
        """

        source_sample = []
        sources = self.fetch_source_samples(sample_id)
        seen = set()  # a set to ensure only unique entries
        for row in sources:
            entry = (row[3], row[1], row[2])
            if entry not in seen:
                source_sample.append(
                    {"url": row[3], "name": row[1], "description": row[2]}
                )
                seen.add(entry)

        return source_sample

    def populate_population_samples(self, sample_id: int) -> list:
        """Populating population samples information

        Args:
            sample_id (int): sample id information

        Returns:
            list: A list of dictionary containing the population information
        """

        population_sample = []
        populations = self.fetch_population_samples(sample_id)
        seen = set()
        for row in populations:
            entry = (row[6], row[9], row[2], row[8], row[3], row[1])
            if entry not in seen:
                population_sample.append(
                    {
                        "elasticId": row[6],
                        "superpopulationName": row[9],
                        "name": row[2],
                        "superpopulationCode": row[8],
                        "description": row[3],
                        "code": row[1],
                    }
                )
                seen.add(entry)

        return population_sample

    def populate_datacollection_samples(self, sample_id: int) -> list:
        """Populating data collection sample information

        Args:
            sample_id (int): sample id information

        Returns:
            list: A list of dictionary containing the data collection
        """

        dataCollections = {"dataTypes": [], "dataReusePolicy": None, "title": None}
        dataCollection_sample = []
        datacollections = self.fetch_dataCollections_samples(sample_id)
        seen = set()
        for row in datacollections:
            entry = (row[4], row[2])
            if entry not in seen:
                dataCollections.update({"dataReusePolicy": row[4], "title": row[2]})
                dataCollections[row[0]] = []
                if row[1] not in dataCollections[row[0]]:
                    dataCollections[row[0]].append(row[1])
                if row[0] not in dataCollections["dataTypes"]:
                    dataCollections["dataTypes"].append(row[0])

                    dataCollection_sample.append(dataCollections)

                    seen.add(entry)

        return dataCollection_sample

    def populate_sample_synonyms(self, sample_id: int) -> list[str]:
        """Return unique, non-empty synonyms for a sample."""
        rows = self.fetch_sample_synonyms_sql(sample_id)  # [(synonym,), ...]
        seen = set()
        out: list[str] = []
        for tup in rows or []:
            syn = tup[0] if tup else None
            if syn and syn not in seen:
                seen.add(syn)
                out.append(syn)
        return out

    def build_the_dictionary_structure(self, row: tuple) -> dict[str, Any]:
        """Building the dictionary structure

        Args:
            row (tuple): Row from the fetch samples return

        Returns:
            dict[str, Any]: The updated dictionary
        """

        self.samples_dict.update(
            {
                "biosampleId": row[2],
                "sex": row[3],
                "name": row[1],
                "source": self.populate_source_samples(row[0]),
                "populations": self.populate_population_samples(row[0]),
                "dataCollections": self.populate_datacollection_samples(row[0]),
                "synonyms": self.populate_sample_synonyms(row[0]),
            }
        )

        return self.samples_dict
