from scripts.compare_schema import EXPECTED_COLUMNS, compare


class CatalogConnection:
    def execute(self, query):
        assert "information_schema.columns" in query
        return CatalogCursor([
            (table, column)
            for table, columns in EXPECTED_COLUMNS.items()
            for column in columns
            if not (table == "knowledge_chunks" and column == "title")
        ])


class CatalogCursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


def test_schema_comparison_finds_the_knowledge_chunk_title_drift():
    diff = compare(CatalogConnection())
    assert diff["knowledge_chunks"] == ({"title"}, set())
    assert all(not missing for table, (missing, _) in diff.items() if table != "knowledge_chunks")
