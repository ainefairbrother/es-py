"""Analysis group details fetcher.

Provides DB accessors to retrieve and assemble information needed to build
`analysis_group` documents for Elasticsearch. This module encapsulates the
SQL query and the shaping of results into a consistent dictionary structure
suitable for indexing.

All functionality is exposed via the `FetchAGFromDB` class.
"""

# ──────────────────────────────────────────────────────────────
# Imports
# ──────────────────────────────────────────────────────────────

from mysql.connector import connect
from typing import Any
from .utils import create_the_dictionary_structure


# ──────────────────────────────────────────────────────────────
# Fetcher
# ──────────────────────────────────────────────────────────────

class FetchAGFromDB:
    """Fetcher for analysis group information."""

    def __init__(self, data: dict[str, Any]):
        """Initialise the fetcher.

        Args:
            data (dict[str, Any]): Configuration data containing database
                connection parameters (e.g., host, port, database, user, password).
        """
        self.data = data

    def fetch_information_from_DB(self) -> list[tuple]:
        """Fetch analysis group information from the database.

        Returns:
            list[tuple]: Rows of analysis group data as returned by MySQL.
        """
        fetch_ag_sql = """SELECT ag.* from file f INNER JOIN analysis_group ag ON f.analysis_group_id = ag.analysis_group_id INNER JOIN sample_file sf on sf.file_id = f.file_id GROUP BY ag.analysis_group_id"""

        host = self.data["host"]
        port = self.data["port"]
        database = self.data["database"]
        password = self.data["password"]
        user = self.data["user"]

        db = connect(
            host=host, port=port, database=database, password=password, user=user
        )
        cursor = db.cursor()
        cursor.execute(fetch_ag_sql)
        ag = cursor.fetchall()
        cursor.close()
        db.close()

        return ag

    def build_ag_info(self, row: tuple) -> dict[str, Any]:
        """Build the analysis group dictionary for indexing.

        Args:
            row (tuple): A single row returned from :meth:`fetch_information_from_DB`.

        Returns:
            dict[str, Any]: Dictionary containing the analysis group fields
                (`code`, `description`, `shortTitle`, `displayOrder`) ready for indexing.
        """
        analysis_group = create_the_dictionary_structure()

        analysis_group.update(
            {
                "code": row[1],
                "description": row[2],
                "shortTitle": row[3],
                "displayOrder": row[4],
            }
        )

        return analysis_group