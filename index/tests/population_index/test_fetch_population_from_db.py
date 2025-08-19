"""
Unit-tests for PopulationDetailsFetcher (population_index).

All database access is mocked with MagicMock so the tests run without a
live MySQL instance.  Helper _patch_mysql() injects canned cursor.rows
into mysql.connector.connect().
"""

import pytest
from unittest.mock import MagicMock
from typing import Any
from pytest_mock import MockerFixture

from index.population_index.fetch_information_from_db import (
    PopulationDetailsFetcher,
)
from index.population_index.utils import create_the_dictionary_structure

# ───────────────────────── Fixtures ──────────────────────────

@pytest.fixture
def db_config() -> dict[str, Any]:
    return {
        "host": "localhost",
        "port": 3306,
        "user": "user",
        "password": "pass",
        "database": "test_db",
    }


@pytest.fixture
def fetcher(db_config: dict[str, Any]) -> PopulationDetailsFetcher:
    return PopulationDetailsFetcher(db_config)


@pytest.fixture
def blank_doc() -> dict[str, Any]:
    return create_the_dictionary_structure()

# ────────────────────────── Tests ────────────────────────────

def _patch_mysql(mocker: MockerFixture, rows):
    """Patch mysql.connector.connect so cursor.fetchall() yields *rows*.

    Args:
        mocker (MockerFixture): The pytest-mocker fixture used to apply the patch.
        rows (list | tuple): Data that cursor.fetchall() should return.
    """
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows
    mock_db = MagicMock()
    mock_db.cursor.return_value = mock_cursor
    mock_db.__enter__.return_value = mock_db
    return mocker.patch("mysql.connector.connect", return_value=mock_db)


def test_fetch_population(mocker: MockerFixture, fetcher: PopulationDetailsFetcher):
    """Test fetch_population returns the expected row.

    Args:
        mocker (MockerFixture): pytest-mocker fixture for patching.
        fetcher (PopulationDetailsFetcher): Instance under test.
    """
    
    rows = [
        (
            "code1", "name1", "desc",
            1.0, 2.0, "eid", 1, 5,
            "spcode", "spname", "#fff", 2, 1
        )
    ]
    _patch_mysql(mocker, rows)

    result = fetcher.fetch_population()
    assert len(result) == 1
    assert result[0][0] == "code1"


def test_fetch_data_collection_details(mocker: MockerFixture, fetcher: PopulationDetailsFetcher):
    """Test fetch_data_collection_details groups rows by population ID.

    Args:
        mocker (MockerFixture): pytest-mocker fixture for patching.
        fetcher (PopulationDetailsFetcher): Instance under test.
    """
    
    # method returns {pop_id: [tuple, ...]}
    rows = [(1, "type1", "group1", "title1", 123, "open")]
    _patch_mysql(mocker, rows)

    res = fetcher.fetch_data_collection_details([1])
    assert 1 in res
    assert res[1][0][0] == "type1"           # dt.code
    assert res[1][0][2] == "title1"          # dc.title


def test_build_population_info(mocker: MockerFixture, fetcher: PopulationDetailsFetcher):
    """Test build_population_info assembles a full population document.

    Args:
        mocker (MockerFixture): pytest-mocker fixture for patching.
        fetcher (PopulationDetailsFetcher): Instance under test.
    """
    
def test_build_population_info(mocker: MockerFixture, fetcher: PopulationDetailsFetcher):
    row = (
        "code", "name", "desc", 1.1, 2.2, "eid",
        0, 10, "spcode", "spname", "#000", 3, 123
    )

    # Use a real dtype key that the code aggregates
    dc_map = {
        123: [("sequence", "grp", "Human Genome", 999, "reuse")]
    }
    overlap_map = {
        123: [(123, "popEL", "Overlap desc", "sharedSample1")]
    }
    mocker.patch.object(fetcher, "fetch_data_collection_details", return_value=dc_map)
    mocker.patch.object(fetcher, "fetch_overlap_population_details", return_value=overlap_map)

    pop_doc = fetcher.build_population_info(row, dc_map, overlap_map)

    assert pop_doc["code"] == "code"
    assert pop_doc["samples"]["count"] == 10

    # dataCollections is now a list; find the "Human Genome" entry
    dc = next(d for d in pop_doc["dataCollections"] if d["title"] == "Human Genome")
    assert "sequence" in dc["dataTypes"]
    assert "grp" in dc["sequence"]

    # overlappingPopulations is now a list, each with its own sharedSampleCount
    assert pop_doc["overlappingPopulations"][0]["sharedSampleCount"] == 1

def test_fetch_overlap_population_details(mocker: MockerFixture, fetcher: PopulationDetailsFetcher):
    """Test fetch_overlap_population_details returns overlaps keyed by ID.

    Args:
        mocker (MockerFixture): pytest-mocker fixture for patching.
        fetcher (PopulationDetailsFetcher): Instance under test.
    """
    
    rows = [
        (
            1,
            "popEl",
            "desc",
            "sampleName",
        )
    ]
    _patch_mysql(mocker, rows)

    result = fetcher.fetch_overlap_population_details([1])
    assert isinstance(result[1], list)
    assert result[1][0][1] == "popEl"