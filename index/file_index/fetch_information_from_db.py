import mysql.connector
from typing import Any
from .utils import create_the_dictionary_structure
from collections import defaultdict

class FetchFileFromDB:
    def __init__(self, db_config: dict):
        self.db_config = db_config

    def fetch_file_from_db(self) -> list[tuple]:
        """Fetches file from DB

        Returns:
            list[tuple]: A list of rows from the db
        """

        fetch_files_sql = """SELECT f.file_id, f.url, f.md5, dt.code, ag.description
    FROM file f LEFT JOIN data_type dt ON f.data_type_id = dt.data_type_id
    LEFT JOIN analysis_group ag ON f.analysis_group_id = ag.analysis_group_id
    ORDER BY file_id"""

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

    def fetch_file_id_from_db(self)-> list:
        """_summary_

        Returns:
            list: _description_
        """        
        fetch_file_id_sql = """SELECT file_id FROM file"""

        db = mysql.connector.connect(
            host=self.db_config["host"],
            port=self.db_config["port"],
            user=self.db_config["user"],
            database=self.db_config["database"],
            password=self.db_config["password"],
        )

        cursor = db.cursor()
        cursor.execute(fetch_file_id_sql)
        file_ids = [row[0] for row in cursor.fetchall()] 
        cursor.close()
        db.close()

        return file_ids

    def fetch_old_files_from_db(self) -> list[tuple]:
        """Fetches old file from the DB

        Returns:
            list[tuple]: A list of rows from the db
        """

        fetch_old_files_sql = """SELECT f.file_id FROM file f
                        WHERE f.foreign_file IS NOT TRUE AND f.in_current_tree IS NOT TRUE AND f.indexed_in_elasticsearch IS TRUE
                        ORDER BY file_id"""

        db = mysql.connector.connect(
            host=self.db_config["host"],
            port=self.db_config["port"],
            user=self.db_config["user"],
            database=self.db_config["database"],
            password=self.db_config["password"],
        )

        cursor = db.cursor()
        cursor.execute(fetch_old_files_sql)
        old_files = cursor.fetchall()
        cursor.close()
        db.close()

        return old_files


    def update_elasticsearch_file(self) -> list[tuple]:
        """Update the column set indexed_in_elasticsearch = 1 based on if foreign file/ in_current_tree is true

        Returns:
            list[tuple]: A list of rows from the db
        """

        update_elasticsearch_sql = """UPDATE file SET indexed_in_elasticsearch = (foreign_file IS TRUE OR in_current_tree IS TRUE)"""

        db = mysql.connector.connect(
            host=self.db_config["host"],
            port=self.db_config["port"],
            user=self.db_config["user"],
            database=self.db_config["database"],
            password=self.db_config["password"],
        )

        cursor = db.cursor()
        cursor.execute(update_elasticsearch_sql)
        db.commit()
        cursor.close()
        db.close()
    

    def preload_data(self, file_ids: list[int]) -> tuple[defaultdict, defaultdict] :
        """Preload data to reduce the number of queries on the database

        Args:
            file_ids (list[int]): List of file_id

        Returns:
            tuple[defaultdict, defaultdict]: Default dict
        """              
        format_strings = ",".join(['%s'] * len(file_ids))

        fetch_datacollections_sql = f"""SELECT fdc.file_id, dc.title, dc.reuse_policy from data_collection dc, file_data_collection fdc
                                        WHERE fdc.data_collection_id=dc.data_collection_id AND fdc.file_id IN ({format_strings})
                                        ORDER BY dc.reuse_policy_precedence"""
        

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
        

        fetch_sample_sql =  f"""SELECT  distinct file_data_collection.file_id, sample.name, population.description AS pop_description 
                            from file_data_collection, sample_file, sample, dc_sample_pop_assign, 
                            population where file_data_collection.file_id IN ({format_strings}) and sample_file.file_id = file_data_collection.file_id  
                            and sample_file.sample_id = sample.sample_id and sample.sample_id=dc_sample_pop_assign.sample_id and 
                            file_data_collection.data_collection_id = dc_sample_pop_assign.data_collection_id and dc_sample_pop_assign.population_id =population.population_id"""

        cursor.execute(fetch_sample_sql, file_ids)
        sp_map = defaultdict(list)
        for file_id, sample, population in cursor.fetchall():
            sp_map[file_id].append((sample, population))

        
        cursor.close()
        db.close()
        return dc_map, sp_map
        
 
    def populate_the_dictionary(self, row: tuple, dc_map: defaultdict, sp_map: defaultdict) -> dict[str, Any]:
        """Populate the file dictionary 

        Args:
            row (tuple): The row from the function fetch_file_from_db
            dc_map (defaultdict): Containing data collection data with file id as the key
            sp_map (defaultdict): Containing samples and population data with file as the key

        Returns:
            dict[str, Any]: Built file dictionary
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
        
        file_dict.update({
            "dataType": row[3],
            "analysisGroup": row[4],
            "url": row[1],
            "md5": row[2],
        })

        return file_dict

