import pytest

from app.config import Settings


@pytest.mark.parametrize(
    "url",
    [
        "postgres://u:p@db.example.com/alphalab?sslmode=require",
        "postgresql://u:p@db.example.com/alphalab?sslmode=require",
        "postgresql+psycopg://u:p@db.example.com/alphalab?sslmode=require",
    ],
)
def test_database_url_always_uses_psycopg(monkeypatch, url):
    monkeypatch.delenv("ALPHALAB_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", url)
    settings = Settings(_env_file=None)
    assert settings.database_url == (
        "postgresql+psycopg://u:p@db.example.com/alphalab?sslmode=require"
    )


def test_alphalab_database_url_takes_precedence(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://hosted/db")
    monkeypatch.setenv("ALPHALAB_DATABASE_URL", "postgresql://local/db")
    assert Settings(_env_file=None).database_url == "postgresql+psycopg://local/db"


@pytest.mark.parametrize("path", ["/health", "/api/health"])
def test_api_prefix_is_optional(client, path):
    assert client.get(path).json() == {"status": "ok"}


def test_only_the_exact_api_prefix_is_stripped(client):
    assert client.get("/apihealth").status_code == 404
