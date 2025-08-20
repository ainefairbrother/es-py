import mysql.connector
from collections import defaultdict
from typing import Any, Dict, List, Tuple
from .utils import create_the_dictionary_structure

class PopulationDetailsFetcher:
    def __init__(self, db_config: dict[str, Any]):
        """Initializing the population details fetcher

        Args:
            db_config (dict): DB configuration dictionary
        """        
        self.db_config = db_config

    def fetch_population(self) -> List[Tuple]:
        """Fetches population information

        Returns:
            List[Tuple]: List of rows containing the population information
        """        
        query = """
            SELECT p.code, p.name, p.description, p.latitude, p.longitude, p.elastic_id, p.display_order,
                   COUNT(DISTINCT sample_id) AS num_samples, sp.code, sp.name, sp.display_colour, 
                   sp.display_order, p.population_id 
            FROM population p
            JOIN superpopulation sp ON p.superpopulation_id = sp.superpopulation_id
            JOIN dc_sample_pop_assign dcsp ON p.population_id = dcsp.population_id
            GROUP BY p.population_id
        """

        with mysql.connector.connect(
            host=self.db_config["host"],
            port=self.db_config["port"],
            database=self.db_config["database"],
            user=self.db_config["user"],
            password=self.db_config["password"],
        ) as db:
            cursor = db.cursor()
            cursor.execute(query)
            return cursor.fetchall()

    def fetch_population_ids(self) -> List[int]:
        """Fetching population ids from the database

        Returns:
            List[int]: List of ids, used to fetch data collection and overlap population details
        """

        query = "SELECT population_id FROM population"

        with mysql.connector.connect(
            host=self.db_config["host"],
            port=self.db_config["port"],
            database=self.db_config["database"],
            user=self.db_config["user"],
            password=self.db_config["password"],
        ) as db:
            cursor = db.cursor()
            cursor.execute(query)
            rows = cursor.fetchall()
            return [row[0] for row in rows]

    def fetch_data_collection_details(
        self, pop_ids: List[int]
    ) -> Dict[int, List[Tuple]]:
        """Fetches data collection details, so it reduces the query to the DB

        Args:
            pop_ids (List[int]): list of pop ids

        Returns:
            Dict[int, List[Tuple]]: A dictionary containing the key and the list of rows from the db
        """        
        if not pop_ids:
            return {}

        placeholders = ",".join(["%s"] * len(pop_ids))
        query = f"""
            SELECT p.population_id, dt.code, ag.description, dc.title, dc.data_collection_id, dc.reuse_policy 
            FROM population p
            JOIN dc_sample_pop_assign dspa ON p.population_id = dspa.population_id
            JOIN sample_file sf ON dspa.sample_id = sf.sample_id
            JOIN file f ON sf.file_id = f.file_id
            JOIN analysis_group ag ON f.analysis_group_id = ag.analysis_group_id
            JOIN data_type dt ON f.data_type_id = dt.data_type_id
            JOIN file_data_collection fdc ON f.file_id = fdc.file_id
            JOIN data_collection dc ON fdc.data_collection_id = dc.data_collection_id
            WHERE p.population_id IN ({placeholders})
            GROUP BY dt.data_type_id, ag.analysis_group_id, dc.data_collection_id, p.population_id
        """

        with mysql.connector.connect(
            host=self.db_config["host"],
            port=self.db_config["port"],
            user=self.db_config["user"],
            database=self.db_config["database"],
            password=self.db_config["password"],
        ) as db:
            cursor = db.cursor()
            cursor.execute(query, pop_ids)
            rows = cursor.fetchall()
            cursor.close()

        results = defaultdict(list)
        for row in rows:
            pop_id = row[0]
            results[pop_id].append(row[1:])

        return results

    def fetch_overlap_population_details(
        self, pop_ids: List[int]
    ) -> Dict[int, List[Dict[str, Any]]]:
        """Fetches overlap population details

        Args:
            pop_ids (List[int]): list of pop ids

        Returns:
            Dict[int, List[Dict[str, Any]]]: A dictionary containing the key and the list of rows from the db
        """        
        if not pop_ids:
            return {}

        placeholders = ",".join(["%s"] * len(pop_ids))

        query = f"""
            SELECT DISTINCT dspa1.population_id AS source_population_id,
                   p.elastic_id AS populationElasticId,
                   p.description AS populationDescription,
                   s.name AS sharedSampleName
            FROM dc_sample_pop_assign dspa1
            JOIN dc_sample_pop_assign dspa2 ON dspa1.sample_id = dspa2.sample_id
            JOIN population p ON dspa2.population_id = p.population_id
            JOIN sample s ON dspa1.sample_id = s.sample_id
            WHERE dspa1.population_id IN ({placeholders})
              AND dspa2.population_id != dspa1.population_id
            ORDER BY dspa1.population_id, p.description, s.name;
        """

        with mysql.connector.connect(
            host=self.db_config["host"],
            port=self.db_config["port"],
            database=self.db_config["database"],
            user=self.db_config["user"],
            password=self.db_config["password"],
        ) as db:
            cursor = db.cursor()
            cursor.execute(query, pop_ids)
            rows = cursor.fetchall()

        results = defaultdict(list)
        for row in rows:
            results[row[0]].append(row)

        return results

    def build_population_info(
        self,
        row: Tuple,
        data_collection_map: Dict[int, List[Tuple]],
        overlap_map: Dict[int, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """Build population information dictionary (doc)

        Args:
            row (Tuple): Result from the fetch_population function
            data_collection_map (Dict[int, List[Tuple]]): Result from the fetch data_collection_details
            overlap_map (Dict[int, List[Dict[str, Any]]]): Result from the overlap_map details

        Returns:
            Dict[str, Any]: Population doc
        """        
        pop_id = row[12]

        population_info = {
            "code": row[0],
            "name": row[1],
            "description": row[2],
            "latitude": float(row[3]),
            "longitude": float(row[4]),
            "elasticId": row[5],
            "display_order": row[6],
            "samples": {"count" : row[7]},
            "superpopulation": {
                "code": row[8],
                "name": row[9],
                "display_color": row[10],
                "display_order": row[11],
            },
            "dataCollections": {
                "dataTypes": [],
            },
            "overlappingPopulations": {
                "sharedSamples": [],
            },
        }

        for dc in data_collection_map.get(pop_id, []):
            data_type, description, title, dc_id, reuse_policy = dc

            if data_type not in population_info["dataCollections"]:
                population_info["dataCollections"][data_type] = []

            if description not in population_info["dataCollections"][data_type]:
                population_info["dataCollections"][data_type].append(description)

            if data_type not in population_info["dataCollections"]["dataTypes"]:
                population_info["dataCollections"]["dataTypes"].append(data_type)

            if not population_info["dataCollections"].get("dataReusePolicy"):
                population_info["dataCollections"]["dataReusePolicy"] = reuse_policy

            if not population_info["dataCollections"].get("title"):
                population_info["dataCollections"]["title"] = title

        overlaps = overlap_map.get(pop_id, [])
        if overlaps:
            population_info["overlappingPopulations"]["populationElasticId"] = overlaps[
                0
            ][1]
            population_info["overlappingPopulations"]["populationDescription"] = (
                overlaps[0][2]
            )
            for row in overlaps:
                if (
                    row[3]
                    not in population_info["overlappingPopulations"]["sharedSamples"]
                ):
                    population_info["overlappingPopulations"]["sharedSamples"].append(
                        row[3]
                    )

            population_info["overlappingPopulations"]["sharedSampleCount"] = len(
                population_info["overlappingPopulations"]["sharedSamples"]
            )

        return population_info
