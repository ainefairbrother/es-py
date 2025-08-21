"""Population details fetcher.

Provides DB accessors to retrieve and assemble information needed to build
`population` documents for Elasticsearch. This module encapsulates the SQL
queries and the shaping of results into a consistent dictionary structure
suitable for indexing.

All functionality is exposed via the `PopulationDetailsFetcher` class.
"""

# ──────────────────────────────────────────────────────────────
# Imports
# ──────────────────────────────────────────────────────────────

import mysql.connector
from collections import defaultdict
from typing import Any, Dict, List, Tuple
from .utils import create_the_dictionary_structure


# ──────────────────────────────────────────────────────────────
# Fetcher
# ──────────────────────────────────────────────────────────────

class PopulationDetailsFetcher:
    """Fetch population metadata and related entities from the database."""

    def __init__(self, db_config: dict[str, Any]):
        """Initialise the population details fetcher.

        Args:
            db_config (dict): Database configuration dictionary with keys
                "host", "port", "database", "user", "password".
        """
        self.db_config = db_config

    def fetch_population(self) -> List[Tuple]:
        """Fetch population summary rows.

        Returns:
            List[Tuple]: Rows containing the population information including
            counts, superpopulation details, and identifiers.
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
        """Fetch population IDs.

        Returns:
            List[int]: Population IDs used to fetch data-collection and
            overlap-population details.
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
        """Fetch data-collection details for populations.

        Preloads data to reduce the number of database queries when building
        population documents.

        Args:
            pop_ids (List[int]): Population IDs.

        Returns:
            Dict[int, List[Tuple]]: Mapping `population_id -> list of tuples`
            where each tuple is `(dt.code, ag.description, dc.title, dc_id, dc.reuse_policy)`.
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
            WHERE p.population_id IN ({placeholders}) AND fdc.data_collection_id = dspa.data_collection_id
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
        """Fetch overlapping-population details.

        Args:
            pop_ids (List[int]): Population IDs.

        Returns:
            Dict[int, List[Dict[str, Any]]]: Mapping `population_id -> list of rows`
            where each row contains overlap information and shared sample names.
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
        """Build a population document for indexing.

        Args:
            row (Tuple): A row from `fetch_population()`.
            data_collection_map (Dict[int, List[Tuple]]): Preloaded data-collection
                details keyed by population ID.
            overlap_map (Dict[int, List[Dict[str, Any]]]): Preloaded overlap details
                keyed by population ID.

        Returns:
            Dict[str, Any]: Population document ready for indexing.
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
            "samples": {"count": row[7]},
            "superpopulation": {
                "code": row[8],
                "name": row[9],
                "display_colour": row[10],
                "display_order": row[11],
            },
            "dataCollections": [],
            "overlappingPopulations": [],
        }

        # ---------- dataCollections ----------
        # tuples: (dt.code, ag.description, dc.title, dc_id, dc.reuse_policy)
        dc_rows = data_collection_map.get(pop_id, [])

        per_dc = {}  # dc_id -> aggregator
        for dtype, ag_desc, dc_title, dc_id, reuse_policy in dc_rows:
            if not dc_id or not dc_title or not dtype:
                # skip incomplete rows and NULL dtype (prevents "null" key)
                continue
            agg = per_dc.setdefault(
                dc_id,
                {
                    "title": dc_title,
                    "dataReusePolicy": reuse_policy,
                    "sequence": set(),
                    "alignment": set(),
                    "variants": set(),
                },
            )
            if ag_desc and dtype in ("sequence", "alignment", "variants"):
                agg[dtype].add(ag_desc)

        # tuples: (dt.code, ag.description, dc.title, dc_id, dc.reuse_policy)
        for dc_id in sorted(per_dc, key=lambda k: (per_dc[k]["title"] or "", k)):
            b = per_dc[dc_id]
            entry = {"title": b["title"]}
            # add dtype buckets if non-empty
            for key in ("sequence", "alignment", "variants"):
                if b[key]:
                    entry[key] = sorted(b[key])
            # dataTypes derived from present buckets
            dtypes = [k for k in ("sequence", "alignment", "variants") if k in entry]
            if dtypes:
                entry["dataTypes"] = dtypes
            entry["dataReusePolicy"] = b.get("dataReusePolicy")
            population_info["dataCollections"].append(entry)

        # ---------- overlappingPopulations ----------
        # rows: (source_population_id, overlap.elastic_id, overlap.description, shared_sample_name)
        ov_rows = overlap_map.get(pop_id, [])
        by_overlap = {}
        for _src, ov_elastic_id, ov_desc, sample_name in ov_rows:
            if not ov_elastic_id:
                continue
            agg = by_overlap.setdefault(
                ov_elastic_id,
                {
                    "populationElasticId": ov_elastic_id,
                    "populationDescription": ov_desc,
                    "sharedSamples": set(),
                },
            )
            if sample_name:
                agg["sharedSamples"].add(sample_name)

        for k in sorted(
            by_overlap,
            key=lambda kk: (by_overlap[kk]["populationDescription"] or "", kk),
        ):
            b = by_overlap[k]
            samples = sorted(b["sharedSamples"])
            population_info["overlappingPopulations"].append(
                {
                    "populationElasticId": b["populationElasticId"],
                    "populationDescription": b["populationDescription"],
                    "sharedSamples": samples,
                    "sharedSampleCount": len(samples),
                }
            )

        return population_info