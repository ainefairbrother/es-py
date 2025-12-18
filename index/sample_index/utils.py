from typing import Any


def create_the_dictionary_structure() -> dict[str, Any]:
    """Create the document structure for the sample

    Returns:
        dict[str, Any]: A dictionary containing a str as a key and any variable as a value
    """
    samples_info = {
        "source": [],
        "biosampleId": None,
        "populations": [],
        "name": None,
        "dataCollections": [],
        "sex": None,
        "relatedSample": [],
        "synonyms": [],
    }

    return samples_info
