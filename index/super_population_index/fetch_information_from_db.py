from mysql.connector import connect
from typing import Any
from .utils import create_the_dictionary_structure

class FetchSPFromDB:
    """Fetching the Superpopulation from Database class"""

    def __init__(self, data: dict[str, Any]):
        """Initializes the class

        Args:
            data (dict[str, Any]): Takes the configuration data
        """
        self.data = data

    def fetch_information_from_db(self) -> list[tuple]:
        """Fetching superpopulation information from DB

        Returns:
            list(tuple) - Returns a list of tuples from the database
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
        """Build superpopulation dictionary

        Args:
            row (tuple): Information from the DB

        Returns:
            dict[str, Any]: Updated dictionary
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