from typing import Any

def create_the_dictionary_structure() -> dict[str, Any]:
    """Return an empty-but-valid population document."""
    return {
        "elasticId": None,
        "name": None,
        "description": None,
        "latitude": None,
        "longitude": None,
        "display_order": None,
        "samples": { "count": 0 },

        "superpopulation": {
            "code": None,
            "name": None,
            "display_color": None,
            "display_order": None,
        },

        # these may stay empty
        "dataCollections": [],
        "overlappingPopulations": {
            "sharedSampleCount": 0,
            "sharedSamples": []
        },
    }