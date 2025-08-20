import pytest
from unittest.mock import MagicMock
from index.sample_index.fetch_samples_from_db import SampleDetailsFetcher
from typing import Any
from pytest_mock import MockerFixture

# ───────────────────────── Fixtures ──────────────────────────

@pytest.fixture
def db_config()-> dict[str, Any]:
    """DB configuration for tests."""
    return {
        "host": "localhost",
        "port": 3306,
        "user": "user",
        "password": "pass",
        "database": "test_db",
    }

@pytest.fixture
def fetcher(db_config: dict[str, Any]) -> SampleDetailsFetcher:
    """Fetcher instance under test."""
    return SampleDetailsFetcher(db_config)

# ────────────────────────── Helpers ──────────────────────────

def _patch_conn(mocker: MockerFixture, fetcher: SampleDetailsFetcher, rows):
    """
    Patch fetcher._get_conn() so cursor.fetchall() yields *rows*.
    """
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = rows
    mock_db = MagicMock()
    mock_db.cursor.return_value = mock_cursor
    mocker.patch.object(fetcher, "_get_conn", return_value=mock_db)
    return mock_db

# ────────────────────────── Tests ────────────────────────────

def test_fetch_samples(mocker: MockerFixture, fetcher: SampleDetailsFetcher):
    """fetch_samples returns expected rows."""
    rows = [(1, "Sample1", "TEST123", "M")]
    _patch_conn(mocker, fetcher, rows)

    result = fetcher.fetch_samples()
    assert len(result) == 1
    assert result[0][2] == "TEST123"


def test_preload_sources(mocker: MockerFixture, fetcher: SampleDetailsFetcher):
    """preload_sources returns mapping with expected tuple layout."""
    # preload_sources SQL returns: (sample_id, sample_source_id, name, description, url)
    rows = [(1, 10, "test_source", "test source description", "http:/test_source_url")]
    _patch_conn(mocker, fetcher, rows)

    res_map = fetcher.preload_sources([1])
    assert 1 in res_map
    first = res_map[1][0]  # (sample_source_id, name, description, url)
    assert first[1] == "test_source"
    assert first[2] == "test source description"


def test_preload_populations(mocker: MockerFixture, fetcher: SampleDetailsFetcher):
    """preload_populations returns rows shaped like the legacy fetch (without sample_id)."""
    # preload_populations SQL yields:
    # (sample_id,
    #  population_id, code, name, desc, lat, lng, elastic_id,
    #  superpop_id, superpop_code, superpop_name, superpop_display_colour, superpop_display_order)
    rows = [(
        1,              # sample_id
        123,            # population_id
        "GBR",          # code
        "Great Britian",
        "Britain",
        "Britain, Scotland and Ireland",
        None,           # lng
        None,           # elastic_id
        "BR",           # superpop_id (note: just matching test shape)
        2,              # superpop_code
        "SUPERGBR",     # superpop_name
        "Super GBR",    # display_colour
        None,           # display_order
    )]
    _patch_conn(mocker, fetcher, rows)

    res_map = fetcher.preload_populations([1])
    assert 1 in res_map
    tup = res_map[1][0]  # this is row[1:] from above (no sample_id)
    # Matches the original assertions against legacy fetch_population_samples()
    assert tup[1] == "GBR"     # code
    assert tup[6] is None      # elastic_id


def test_preload_datacollections(mocker: MockerFixture, fetcher: SampleDetailsFetcher):
    """preload_datacollections returns expected tuple layout per sample."""
    # preload_datacollections SQL returns:
    # (sample_id, dt.code, ag.description, dc.title, dc_id, dc.reuse_policy)
    rows = [(1, "test_igsr", "test pacbio sequence", "test igsr", 1, None)]
    _patch_conn(mocker, fetcher, rows)

    res_map = fetcher.preload_datacollections([1])
    assert 1 in res_map
    tup = res_map[1][0]  # (dt.code, ag.description, title, id, policy)
    assert tup[0] == "test_igsr"
    assert tup[4] is None