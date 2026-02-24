from app import get_auth_header, construir_arbol

def test_get_auth_header_ok():
    header = get_auth_header("TOKEN123")

    assert header is not None
    assert "Authorization" in header
    assert header["Accept"] == "application/hal+json"

def test_get_auth_header_none():
    assert get_auth_header(None) is None


def test_construir_arbol_simple():
    projects = [
        {"id": 1, "_links": {}},
        {"id": 2, "_links": {"parent": {"href": "/api/v3/projects/1"}}}
    ]

    arbol = construir_arbol(projects)

    assert len(arbol) == 1
    assert arbol[0]["id"] == 1
    assert arbol[0]["children"][0]["id"] == 2