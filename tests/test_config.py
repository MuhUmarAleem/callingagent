from app.config import normalize_database_url


class TestNormalizeDatabaseUrl:
    def test_postgres_scheme(self):
        assert normalize_database_url(
            "postgres://user:pass@host:5432/db"
        ) == "postgresql+psycopg://user:pass@host:5432/db"

    def test_postgresql_scheme(self):
        assert normalize_database_url(
            "postgresql://user:pass@host:5432/db"
        ) == "postgresql+psycopg://user:pass@host:5432/db"

    def test_already_psycopg(self):
        url = "postgresql+psycopg://user:pass@host:6543/db"
        assert normalize_database_url(url) == url

    def test_empty(self):
        assert normalize_database_url("") == ""
