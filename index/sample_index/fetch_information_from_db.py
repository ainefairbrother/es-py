"""Sample details fetcher.

Provides DB accessors to retrieve and assemble information needed to build
`sample` documents for Elasticsearch. This module encapsulates SQL queries,
batched preloading, and shaping of results into a consistent dictionary
structure suitable for indexing.

All functionality is exposed via the `SampleDetailsFetcher` class.
"""

# ──────────────────────────────────────────────────────────────
# Imports
# ──────────────────────────────────────────────────────────────

from mysql.connector import connect
from typing import Any, Iterable
from index.sample_index.utils import create_the_dictionary_structure


# ──────────────────────────────────────────────────────────────
# Fetcher
# ──────────────────────────────────────────────────────────────


class SampleDetailsFetcher:
    """Fetch sample metadata and related entities from the database."""

    def __init__(self, db_config: dict):
        """Initialise the fetcher with database configuration.

        Args:
            db_config (dict): Database configuration with keys "host", "port",
                "database", "user", "password".
        """
        self.db_config = db_config
        self._conn = None  # single reused connection

    # ───────────────────────── DB connection helpers ─────────────────────────
    def _get_conn(self):
        """Return a live MySQL connection, reconnecting if necessary.

        Reuses a single connection across calls, attempting a light reconnect
        if the connection has dropped. Falls back to creating a fresh connection
        if the reconnect fails.
        """
        if self._conn is None:
            self._conn = connect(
                host=self.db_config["host"],
                port=self.db_config["port"],
                database=self.db_config["database"],
                user=self.db_config["user"],
                password=self.db_config["password"],
            )
        else:
            try:
                if not self._conn.is_connected():
                    self._conn.reconnect(attempts=2, delay=0.2)
            except Exception:
                try:
                    self._conn.close()
                finally:
                    self._conn = connect(
                        host=self.db_config["host"],
                        port=self.db_config["port"],
                        database=self.db_config["database"],
                        user=self.db_config["user"],
                        password=self.db_config["password"],
                    )
        return self._conn

    def close(self):
        """Close the underlying connection (if open) and reset state."""
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    # ───────────────────────────── queries ─────────────────────────────
    def fetch_samples(self) -> list[tuple]:
        """Fetch base sample rows.

        Returns:
            list[tuple]: Rows of `(sample_id, name, biosample_id, sex)`.
        """
        sql = "SELECT s.sample_id, s.name, s.biosample_id, s.sex FROM sample s"
        db = self._get_conn()
        cur = db.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cur.close()
        return rows

    # ─────────────── batch preloads ────────────────────────────────────
    @staticmethod
    def _chunks(ids: list[int], size: int = 1000) -> Iterable[list[int]]:
        """Yield slices of `ids` of at most `size` elements.

        Args:
            ids (list[int]): Identifiers to split into chunks.
            size (int): Maximum chunk size.

        Yields:
            list[int]: Chunk of identifiers.
        """
        for i in range(0, len(ids), size):
            yield ids[i : i + size]

    def preload_sources(self, sample_ids: list[int]) -> dict[int, list[tuple]]:
        """Preload sample sources for a batch of sample IDs.

        Produces a mapping suitable for fast document construction without
        per-sample queries.

        Args:
            sample_ids (list[int]): Sample identifiers.

        Returns:
            dict[int, list[tuple]]: Map `sample_id -> [(sample_source_id, name, description, url), ...]`.
        """
        if not sample_ids:
            return {}
        out: dict[int, list[tuple]] = {}
        db = self._get_conn()
        for batch in self._chunks(sample_ids):
            placeholders = ",".join(["%s"] * len(batch))
            sql = f"""
                SELECT s.sample_id, ss.sample_source_id, ss.name, ss.description, ss.url
                FROM sample s
                JOIN sample_source ss ON s.sample_source_id = ss.sample_source_id
                WHERE s.sample_id IN ({placeholders})
            """
            cur = db.cursor()
            cur.execute(sql, batch)
            for sid, src_id, name, desc, url in cur.fetchall():
                out.setdefault(sid, []).append((src_id, name, desc, url))
            cur.close()
        return out

    def preload_populations(self, sample_ids: list[int]) -> dict[int, list[tuple]]:
        """Preload populations for a batch of sample IDs.

        Returns rows in the same shape as `fetch_population_samples()` (but with
        `sample_id` included and then dropped so offsets match the old builder).

        Args:
            sample_ids (list[int]): Sample identifiers.

        Returns:
            dict[int, list[tuple]]: Map `sample_id -> rows` matching the legacy shape.
        """
        if not sample_ids:
            return {}
        out: dict[int, list[tuple]] = {}
        db = self._get_conn()
        for batch in self._chunks(sample_ids):
            placeholders = ",".join(["%s"] * len(batch))
            sql = f"""
                SELECT dspa.sample_id,
                       population.population_id, population.code, population.name, population.description,
                       population.latitude, population.longitude, population.elastic_id,
                       population.superpopulation_id, superpopulation.code, superpopulation.name,
                       superpopulation.display_colour, superpopulation.display_order
                FROM dc_sample_pop_assign dspa
                JOIN population ON dspa.population_id = population.population_id
                JOIN superpopulation ON population.superpopulation_id = superpopulation.superpopulation_id
                WHERE dspa.sample_id IN ({placeholders})
            """
            cur = db.cursor()
            cur.execute(sql, batch)
            for row in cur.fetchall():
                sid = row[0]
                out.setdefault(sid, []).append(
                    row[1:]
                )  # drop sid to match old builder offsets
            cur.close()
        return out

    def preload_datacollections(self, sample_ids: list[int]) -> dict[int, list[tuple]]:
        """Preload data collections linked to samples.

        Args:
            sample_ids (list[int]): Sample identifiers.

        Returns:
            dict[int, list[tuple]]: Map `sample_id -> rows` in the shape
            `(dt.code, ag.description, dc.title, dc_id, dc.reuse_policy)`.
        """
        if not sample_ids:
            return {}
        out: dict[int, list[tuple]] = {}
        db = self._get_conn()
        for batch in self._chunks(sample_ids):
            placeholders = ",".join(["%s"] * len(batch))
            sql = f"""
                SELECT sf.sample_id, dt.code, ag.description, dc.title, dc.data_collection_id, dc.reuse_policy
                FROM file f
                LEFT JOIN data_type dt ON f.data_type_id = dt.data_type_id
                LEFT JOIN analysis_group ag ON f.analysis_group_id = ag.analysis_group_id
                INNER JOIN sample_file sf ON sf.file_id = f.file_id
                INNER JOIN file_data_collection fdc ON f.file_id = fdc.file_id
                INNER JOIN data_collection dc ON fdc.data_collection_id = dc.data_collection_id
                WHERE sf.sample_id IN ({placeholders})
                GROUP BY sf.sample_id, dt.data_type_id, ag.analysis_group_id, dc.data_collection_id
            """
            cur = db.cursor()
            cur.execute(sql, batch)
            for row in cur.fetchall():
                sid = row[0]
                out.setdefault(sid, []).append(
                    row[1:]
                )  # drop sid to reuse same builder
            cur.close()
        return out

    def preload_relationships(self, sample_ids: list[int]) -> dict[int, list[tuple]]:
        """Preload sample relationships for a batch of sample IDs.

        Args:
            sample_ids (list[int]): Sample identifiers.

        Returns:
            dict[int, list[tuple]]: Map `sample_id -> [(related_name, relationship_type), ...]`.
        """
        if not sample_ids:
            return {}
        out: dict[int, list[tuple]] = {}
        db = self._get_conn()
        for batch in self._chunks(sample_ids):
            placeholders = ",".join(["%s"] * len(batch))
            sql = f"""
                SELECT sr.subject_sample_id AS sample_id, s.name, sr.type
                FROM sample_relationship sr
                JOIN sample s ON sr.relation_sample_id = s.sample_id
                WHERE sr.subject_sample_id IN ({placeholders})
            """
            cur = db.cursor()
            cur.execute(sql, batch)
            for sid, name, reltype in cur.fetchall():
                out.setdefault(sid, []).append((name, reltype))
            cur.close()
        return out

    def preload_synonyms(self, sample_ids: list[int]) -> dict[int, list[str]]:
        """Preload sample synonyms for a batch of sample IDs.

        Args:
            sample_ids (list[int]): Sample identifiers.

        Returns:
            dict[int, list[str]]: Map `sample_id -> [synonym, ...]`.
        """
        if not sample_ids:
            return {}
        out: dict[int, list[str]] = {}
        db = self._get_conn()
        for batch in self._chunks(sample_ids):
            placeholders = ",".join(["%s"] * len(batch))
            sql = f"SELECT sample_id, synonym FROM sample_synonym WHERE sample_id IN ({placeholders})"
            cur = db.cursor()
            cur.execute(sql, batch)
            for sid, syn in cur.fetchall():
                if syn:
                    out.setdefault(sid, []).append(syn)
            cur.close()
        return out

    # ─────────────────────────── builders ──────────────────────────────
    @staticmethod
    def _build_sources(rows: list[tuple]) -> list[dict[str, Any]]:
        """Build the `source` subdocument list.

        Args:
            rows (list[tuple]): Rows from `preload_sources` or per-sample fetch.

        Returns:
            list[dict[str, Any]]: De-duplicated list of `{"url","name","description"}`.
        """
        out, seen = [], set()
        for _sid, name, desc, url in (
            (None, r[2], r[3], r[4]) if len(r) == 5 else (None, r[1], r[2], r[3])
            for r in rows
        ):
            key = (url, name, desc)
            if key in seen:
                continue
            seen.add(key)
            out.append({"url": url, "name": name, "description": desc})
        return out

    @staticmethod
    def _build_populations(rows: list[tuple]) -> list[dict[str, Any]]:
        """Build the `populations` subdocument list.

        Args:
            rows (list[tuple]): Rows from `preload_populations` (legacy layout).

        Returns:
            list[dict[str, Any]]: Population entries referencing elastic and
            superpopulation identifiers.
        """
        out, seen = [], set()
        for row in rows:
            # row layout matches fetch_population_samples() (without sample_id)
            code, name, desc = row[1], row[2], row[3]
            elastic_id = row[6]
            sp_code, sp_name = row[8], row[9]
            key = (elastic_id, sp_name, name, sp_code, desc, code)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "elasticId": elastic_id,
                    "superpopulationName": sp_name,
                    "name": name,
                    "superpopulationCode": sp_code,
                    "description": desc,
                    "code": code,
                }
            )
        return out

    @staticmethod
    def _build_datacollections(rows: list[tuple]) -> list[dict[str, Any]]:
        """Build the `dataCollections` subdocument list.

        Args:
            rows (list[tuple]): `(dt.code, ag.description, dc.title, dc_id, dc.reuse_policy)`.

        Returns:
            list[dict[str, Any]]: Aggregated list per data collection with
            optional `sequence`, `alignment`, `variants`, and derived
            `dataTypes` fields.
        """
        per_dc: dict[int, dict] = {}
        for dtype, ag_desc, title, dc_id, reuse_policy in rows:
            if not dc_id:
                continue
            if dc_id not in per_dc:
                per_dc[dc_id] = {
                    "title": title,
                    "dataReusePolicy": reuse_policy,
                    "_dtype_seen": {},
                }
            dc = per_dc[dc_id]
            if dtype:
                dc["_dtype_seen"][dtype] = 1
                if ag_desc:
                    bucket = dc.setdefault(dtype, [])
                    if ag_desc not in bucket:
                        bucket.append(ag_desc)
        out: list[dict] = []
        for dc_id in sorted(per_dc.keys(), key=lambda x: str(x)):
            dc = per_dc[dc_id].copy()
            dtype_list = list(dc.pop("_dtype_seen").keys())
            if dtype_list:
                dc["dataTypes"] = dtype_list
            out.append(dc)
        return out

    @staticmethod
    def _build_relationships(rows: list[tuple]) -> list[dict[str, str]]:
        """Build the `relatedSample` subdocument list.

        Args:
            rows (list[tuple]): `(related_name, relationship_type)`.

        Returns:
            list[dict[str, str]]: Relationship entries.
        """
        out, seen = [], set()
        for name, reltype in rows:
            key = (name, reltype)
            if key in seen:
                continue
            seen.add(key)
            out.append({"relatedSampleName": name, "relationship": reltype})
        return out

    @staticmethod
    def _build_synonyms(rows: list[str]) -> list[str]:
        """Build the `synonyms` list (deduplicated, order-stable)."""
        out, seen = [], set()
        for syn in rows or []:
            if syn and syn not in seen:
                seen.add(syn)
                out.append(syn)
        return out

    # ─────────────── dict builder ───────────────────────────────────────────
    def build_the_dictionary_structure(
        self,
        row: tuple,
        *,
        sources_map: dict[int, list[tuple]] | None = None,
        populations_map: dict[int, list[tuple]] | None = None,
        dcs_map: dict[int, list[tuple]] | None = None,
        rels_map: dict[int, list[tuple]] | None = None,
        syns_map: dict[int, list[str]] | None = None,
    ) -> dict[str, Any]:
        """Construct the full sample document for indexing.

        Falls back to per-sample queries if preloaded maps are not supplied.

        Args:
            row (tuple): Base row from `fetch_samples()`.
            sources_map (dict[int, list[tuple]] | None): Preloaded sources.
            populations_map (dict[int, list[tuple]] | None): Preloaded populations.
            dcs_map (dict[int, list[tuple]] | None): Preloaded data collections.
            rels_map (dict[int, list[tuple]] | None): Preloaded relationships.
            syns_map (dict[int, list[str]] | None): Preloaded synonyms.

        Returns:
            dict[str, Any]: Sample document ready for indexing.
        """
        sample_id, name, biosample_id, sex = row[0], row[1], row[2], row[3]

        # fall back to per-sample fetch if maps not provided
        src_rows = (
            sources_map.get(sample_id, [])
            if sources_map is not None
            else [(None, *r) for r in self.fetch_source_samples(sample_id)]
        )
        pop_rows = (
            populations_map.get(sample_id, [])
            if populations_map is not None
            else self.fetch_population_samples(sample_id)
        )
        dc_rows = (
            dcs_map.get(sample_id, [])
            if dcs_map is not None
            else self.fetch_dataCollections_samples(sample_id)
        )
        rel_rows = (
            rels_map.get(sample_id, [])
            if rels_map is not None
            else self.fetch_relationship_samples(sample_id)
        )
        syn_rows = (
            syns_map.get(sample_id, [])
            if syns_map is not None
            else [r[0] for r in self.fetch_sample_synonyms_sql(sample_id)]
        )

        doc = create_the_dictionary_structure()
        doc.update(
            {
                "biosampleId": biosample_id,
                "sex": sex,
                "name": name,
                "source": self._build_sources(src_rows),
                "populations": self._build_populations(pop_rows),
                "dataCollections": self._build_datacollections(dc_rows),
                "relatedSample": self._build_relationships(rel_rows),
                "synonyms": self._build_synonyms(syn_rows),
            }
        )
        return doc
