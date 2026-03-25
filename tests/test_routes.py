import responses 
from app import BASE_URL

def test_index_get(client):
    response = client.get("/")

    assert response.status_code == 200
    assert b"OpenProject Reporter" in response.data

def test_index_post_sin_token(client):
    response = client.post("/", data={"token": ""})

    assert response.status_code == 200
    assert b"token de API" in response.data

@responses.activate
def test_index_post_con_proyectos(client):

    responses.add(
        responses.GET,
        f"{BASE_URL}/api/v3/projects",
        json={
            "_embedded": {
                "elements": [
                    {"id": 1, "name": "Proyecto A", "_links": {}}
                ]
            }
        },
        status=200
    )

    response = client.post("/", data={"token": "abc123"})

    assert response.status_code == 200
    assert b"Proyecto A" in response.data

@responses.activate
def test_proyecto_miembros(client):

    # Simular sesión autenticada
    with client.session_transaction() as sess:
        sess["op_token"] = "token"

    # Mock memberships
    responses.add(
        responses.GET,
        f"{BASE_URL}/api/v3/memberships",
        json={
            "_embedded": {
                "elements": [
                    {
                        "_links": {
                            "roles": [{"title": "Jefe de proyecto"}],
                            "principal": {
                                "title": "Ana",
                                "href": "/api/v3/users/1"
                            }
                        }
                    }
                ]
            }
        },
        status=200
    )

    # Mock usuario
    responses.add(
        responses.GET,
        f"{BASE_URL}/api/v3/users/1",
        json={"name": "Ana", "email": "ana@ugr.es"},
        status=200
    )

    response = client.get("/proyecto/1/miembros")

    data = response.get_json()

    assert response.status_code == 200
    assert data["jefes"][0]["nombre"] == "Ana"
    assert data["jefes"][0]["email"] == "ana@ugr.es"