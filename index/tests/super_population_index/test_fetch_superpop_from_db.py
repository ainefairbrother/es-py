import pytest
from unittest.mock import MagicMock, patch
from index.super_population_index.fetch_information_from_db import FetchSPFromDB
from pytest_mock import MockerFixture
from typing import Any

# ───────────────────────── Fixtures ──────────────────────────

@pytest.fixture
def db_config() -> dict[str, Any]:
    """DB configuration

    Returns:
        dict: Dictionary containing the test db configuration
    """
    return {
        "host": "localhost",
        "port": 3306,
        "user": "user",
        "password": "pass",
        "database": "test_db",
    }


@pytest.fixture
def fetcher(db_config: dict[str, Any])-> FetchSPFromDB:
    """The fetcher fixture

    Args:
        db_config (dict): DB configuration

    Returns:
        FetchSPFromDB:  A class
    """    
    return FetchSPFromDB(db_config)

# ────────────────────────── Tests ────────────────────────────

def test_fetch_information_from_db(mocker: MockerFixture, fetcher:FetchSPFromDB):
    """Test for FetchSPFromDB - fetch_information_from_DB

    Args:
        mocker (MockerFixture): Mocker from the Pytest_mock:MockerFixture
        fetcher (FetchSPFromDB): FetchSPFromDB class
    """    
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        ("TEST", "Test ancestry", None, None)
    ]

    mock_db = mock_cursor
    mock_db.cursor.return_value = mock_cursor
    mocker.patch(
        "index.super_population_index.fetch_information_from_db.connect",
        return_value=mock_db
    )
    result = fetcher.fetch_information_from_db()
    assert result[0][0] == "TEST"
    assert isinstance(result, list)


def test_build_superpopulation_info(mocker: MockerFixture, fetcher: FetchSPFromDB):
    """Test for FetchSPFromDB - build_superpopulation_info

    Args:
        mocker (MockerFixture): Mocker from the Pytest_mock:MockerFixture
        fetcher (FetchSPFromDB): FetchSPFromDB class
    """    
    row = ("TEST", "Test ancestry", None, None)

    result = fetcher.build_superpopulation_info(row)

    assert result["elasticId"] == "TEST"
    assert result["name"] == "Test ancestry"
