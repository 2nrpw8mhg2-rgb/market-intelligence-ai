from app.database.repositories import _chunks


def test_bulk_rows_are_chunked_below_asyncpg_parameter_limit() -> None:
    rows = [{"value": index} for index in range(2_501)]
    chunks = list(_chunks(rows))
    assert [len(item) for item in chunks] == [1_000, 1_000, 501]
