import pytest
from unittest.mock import MagicMock, patch
from typing import Any
from index.analysis_group_index.fetch_information_from_db import FetchAGFromDB

# ───────────────────────── Fixtures ──────────────────────────


@pytest.fixture
def db_config() -> dict[str, Any]:
    """Fixture for the db configuration

    Returns:
        dict[str, Any]: The configuration dictionary
    """
    return {
        "host": "localhost",
        "port": 3306,
        "user": "user",
        "password": "pass",
        "database": "test_db",
    }


@pytest.fixture
def fetcher(db_config: dict[str, Any]) -> FetchAGFromDB:
    """Fixture for the fetcher

    Args:
        db_config (dict[str, Any]): The configuration dictionary

    Returns:
        FetchAGFromDB: FetchAGFromDB class
    """

    return FetchAGFromDB(db_config)


# ────────────────────────── Tests ────────────────────────────


def test_fetch_information_from_db(mocker, fetcher: FetchAGFromDB):
    """Test for fetching information from DB

    Args:
        mocker (MockerFixture): Mocker for the DB
        fetcher (FetchAGFromDB): FetchAGFromDB class
    """
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [
        (1, "test_exome", "Test exome", "test-exome", 2, None)
    ]
    mock_db = MagicMock()
    mock_db.cursor.return_value = mock_cursor
    mocker.patch(
        "index.analysis_group_index.fetch_information_from_db.connect",
        return_value=mock_db,
    )

    result = fetcher.fetch_information_from_DB()
    assert result[0][1] == "test_exome"


def test_build_ag_info(fetcher: FetchAGFromDB):
    """Test for the FetchAGFromDB- test_build_ag_info

    Args:
        fetcher (FetchAGFromDB): FetchAGFromDB class
    """
    return_value = (1, "test_exome", "Test exome", "test-exome", 2, None)

    result = fetcher.build_ag_info(return_value)

    assert result["code"] == "test_exome"
    assert result["description"] == "Test exome"
