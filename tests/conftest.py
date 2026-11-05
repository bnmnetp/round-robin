import pytest
from fastapi.testclient import TestClient

from rr.main import create_app

PASSWORD = "court-sweep"


@pytest.fixture
def app(tmp_path):
    return create_app(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        admin_password=PASSWORD,
        secret_key="test-secret",
        https_only=False,
    )


@pytest.fixture
def db(app):
    with app.state.Session() as session:
        yield session


@pytest.fixture
def client(app):
    """A visitor who isn't logged in."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def organizer(app):
    with TestClient(app) as c:
        r = c.post("/login", data={"password": PASSWORD}, follow_redirects=False)
        assert r.status_code == 303
        yield c
