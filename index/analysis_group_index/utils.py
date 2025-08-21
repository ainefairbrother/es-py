from typing import Any


def create_the_dictionary_structure() -> dict[str, Any]:
    """Creates the dictionary structure for the analysis group

    Returns:
        dict[str, Any]: An initialized dictionary
    """

    analysis_group = {
        "code": None,
        "description": None,
        "shortTitle": None,
        "displayOrder": None,
    }

    return analysis_group
