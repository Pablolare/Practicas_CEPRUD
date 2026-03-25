import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import pytest
from app import app

@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test_key"

    with app.test_client() as client:
        yield client