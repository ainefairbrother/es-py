"""Superpopulation details fetcher.

Provides DB accessors to retrieve and assemble information needed to build
`superpopulation` documents for Elasticsearch. This module encapsulates SQL
queries and the shaping of results into a consistent dictionary structure
suitable for indexing.

All functionality is exposed via the `FetchSPFromDB` class.
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

class FetchSPFromDB:
    """Fetch superpopulation metadata from the database."""

    def __init__(self, data: dict[str, Any]):
        """Initialise the fetcher with configuration.

        Args:
            data (dict[str, Any]): Configuration containing DB connection
                parameters (host, port, database, user, password).
        """
        self.data = data

    def fetch_information_from_db(self) -> list[tuple]:
        """Fetch superpopulation rows from the database.

        Returns:
            list[tuple]: List of tuples representing superpopulation rows.
        """
        # not using code because code is sometimes null
        select_superpop_sql = """SELECT sp.elastic_id, sp.name, sp.display_colour, sp.display_order from superpopulation sp GROUP BY sp.superpopulation_id"""

        host = self.data["host"]
        port = self.data["port"]
        database = self.data["database"]
        password = self.data["password"]
        user = self.data["user"]

        db = connect(
            host=host, port=port, user=user, password=password, database=database
        )
        cursor = db.cursor()
        cursor.execute(select_superpop_sql)
        superpopulation = cursor.fetchall()
        cursor.close()
        db.close()

        return superpopulation

    def build_superpopulation_info(self, row: tuple) -> dict[str, Any]:
        """Build the superpopulation document.

        Args:
            row (tuple): Tuple of values from the database query.

        Returns:
            dict[str, Any]: Dictionary representing a superpopulation document.
        """
        superpopulation = create_the_dictionary_structure()
        superpopulation.update(
            {
                "elastic_id": row[0],
                "name": row[1],
                "display_colour": row[2],
                "display_order": row[3],
            }
        )

        return superpopulation