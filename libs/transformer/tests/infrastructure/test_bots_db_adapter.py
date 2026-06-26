from unittest.mock import MagicMock

import pytest
from transformer.infrastructure.adapters.bots_db_adapter import SqlAlchemyBotsDatabaseAdapter


@pytest.fixture
def mock_session():
    return MagicMock()


@pytest.fixture
def adapter(mock_session):
    return SqlAlchemyBotsDatabaseAdapter(mock_session)


def test_query_fetches_all_records(adapter, mock_session):
    mock_cursor = MagicMock()
    mock_connection = MagicMock()
    mock_connection.connection.cursor.return_value = mock_cursor
    mock_session.connection.return_value = mock_connection

    mock_cursor.description = [("id",), ("name",)]
    mock_cursor.fetchall.return_value = [(1, "Test")]

    result = adapter.query("SELECT * FROM test", "value1")

    mock_cursor.execute.assert_called_once()
    assert result == [{"id": 1, "name": "Test"}]


def test_changeq_executes_commit(adapter, mock_session):
    mock_cursor = MagicMock()
    mock_connection = MagicMock()
    mock_connection.connection.cursor.return_value = mock_cursor
    mock_session.connection.return_value = mock_connection

    adapter.changeq("UPDATE test SET status=1")

    mock_cursor.execute.assert_called_once()
    mock_session.commit.assert_called_once()


def test_unique_generates_nummer(adapter, mock_session):
    mock_cursor = MagicMock()
    mock_connection = MagicMock()
    mock_connection.connection.cursor.return_value = mock_cursor
    mock_session.connection.return_value = mock_connection

    mock_cursor.description = [("nummer",)]
    mock_cursor.fetchone.return_value = (5,)

    nummer = adapter.unique("test_domain")

    # Assert it grabbed the current nummer and returned +1 (6)
    assert nummer == 6
    assert mock_cursor.execute.call_count == 2  # Select + Update
    mock_session.commit.assert_called_once()
