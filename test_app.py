"""
Tests para la aplicación Flask de OpenProject Reporter.
Cubre funciones puras, rutas HTTP y llamadas a la API (con mocks).
Ejecutar con: pytest test_app.py -v
"""
import pytest
from unittest.mock import patch, MagicMock
from app import app, get_auth_header, parse_horas, construir_arbol, construir_arbol_sesion


# ─── Fixture: cliente de pruebas Flask ────────────────────────────────────────

@pytest.fixture
def client():
    """Cliente HTTP de Flask configurado para tests."""
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test_secret"
    with app.test_client() as client:
        yield client


@pytest.fixture
def client_autenticado(client):
    """Cliente con sesión de usuario ya iniciada (token simulado)."""
    with client.session_transaction() as sess:
        sess["op_token"] = "token_de_prueba"
        sess["proyectos"] = [
            {"id": 1, "name": "Proyecto A", "parent_id": None},
            {"id": 2, "name": "Proyecto B", "parent_id": 1},
        ]
    return client


# ─── Tests: get_auth_header ───────────────────────────────────────────────────

def test_get_auth_header_con_token():
    """Debe devolver un dict con Authorization y Accept."""
    header = get_auth_header("mi_token")
    assert header is not None
    assert "Authorization" in header
    assert header["Authorization"].startswith("Basic ")
    assert header["Accept"] == "application/hal+json"


def test_get_auth_header_sin_token():
    """Sin token debe devolver None."""
    assert get_auth_header(None) is None
    assert get_auth_header("") is None


def test_get_auth_header_formato_base64():
    """El contenido Base64 debe codificar 'apikey:<token>'."""
    import base64
    header = get_auth_header("abc123")
    b64 = header["Authorization"].replace("Basic ", "")
    decoded = base64.b64decode(b64).decode()
    assert decoded == "apikey:abc123"


# ─── Tests: parse_horas ───────────────────────────────────────────────────────

def test_parse_horas_float():
    """Valor numérico directo."""
    assert parse_horas(2.5) == 2.5
    assert parse_horas("3.0") == 3.0


def test_parse_horas_iso_solo_horas():
    """Formato ISO 'PT2H' → 2.0 horas."""
    assert parse_horas("PT2H") == 2.0


def test_parse_horas_iso_horas_y_minutos():
    """Formato ISO 'PT1H30M' → 1.5 horas."""
    assert parse_horas("PT1H30M") == 1.5


def test_parse_horas_iso_solo_minutos():
    """Formato ISO 'PT30M' → 0.5 horas."""
    assert parse_horas("PT30M") == 0.5


def test_parse_horas_valor_invalido():
    """Valor no reconocible debe devolver 0.0."""
    assert parse_horas(None) == 0.0
    assert parse_horas("invalido") == 0.0


# ─── Tests: construir_arbol ───────────────────────────────────────────────────

def test_construir_arbol_sin_padre():
    """Proyectos sin padre deben ser todos raíces."""
    proyectos = [
        {"id": 1, "name": "P1", "_links": {"parent": {}}},
        {"id": 2, "name": "P2", "_links": {"parent": {}}},
    ]
    raices = construir_arbol(proyectos)
    assert len(raices) == 2
    assert all(p["children"] == [] for p in raices)


def test_construir_arbol_con_hijos():
    """Un proyecto con parent_href debe quedar como hijo de su padre."""
    proyectos = [
        {"id": 1, "name": "Padre", "_links": {"parent": {}}},
        {"id": 2, "name": "Hijo",  "_links": {"parent": {"href": "/api/v3/projects/1"}}},
    ]
    raices = construir_arbol(proyectos)
    assert len(raices) == 1
    assert raices[0]["name"] == "Padre"
    assert len(raices[0]["children"]) == 1
    assert raices[0]["children"][0]["name"] == "Hijo"


def test_construir_arbol_padre_fuera_de_lista():
    """Si el padre no está en la lista, el hijo se trata como raíz."""
    proyectos = [
        {"id": 5, "name": "Huérfano", "_links": {"parent": {"href": "/api/v3/projects/99"}}},
    ]
    raices = construir_arbol(proyectos)
    assert len(raices) == 1
    assert raices[0]["name"] == "Huérfano"


# ─── Tests: construir_arbol_sesion ────────────────────────────────────────────

def test_construir_arbol_sesion_basico():
    """Debe anidar correctamente usando parent_id."""
    proyectos = [
        {"id": 1, "name": "Raíz",  "parent_id": None},
        {"id": 2, "name": "Hijo1", "parent_id": 1},
        {"id": 3, "name": "Hijo2", "parent_id": 1},
    ]
    raices = construir_arbol_sesion(proyectos)
    assert len(raices) == 1
    assert len(raices[0]["children"]) == 2


def test_construir_arbol_sesion_lista_vacia():
    """Lista vacía debe devolver lista vacía."""
    assert construir_arbol_sesion([]) == []


# ─── Tests: rutas (sin autenticación) ─────────────────────────────────────────

def test_index_get(client):
    """GET / debe devolver 200."""
    r = client.get("/")
    assert r.status_code == 200


def test_index_post_token_vacio(client):
    """POST / sin token debe mostrar error en la página."""
    r = client.post("/", data={"token": ""})
    assert r.status_code == 200
    assert "token" in r.data.decode().lower()


def test_logout_redirige(client):
    """GET /logout debe redirigir al index."""
    r = client.get("/logout")
    assert r.status_code == 302
    assert "/" in r.headers["Location"]


def test_informe_sin_token_redirige(client):
    """GET /informe sin sesión debe redirigir al index."""
    r = client.get("/informe")
    assert r.status_code == 302


def test_miembros_sin_token_retorna_401(client):
    """GET /proyecto/<id>/miembros sin token debe devolver 401."""
    r = client.get("/proyecto/1/miembros")
    assert r.status_code == 401


def test_programar_sin_token_redirige(client):
    """GET /programar sin sesión debe redirigir al index."""
    r = client.get("/programar")
    assert r.status_code == 302


# ─── Tests: rutas con sesión activa ───────────────────────────────────────────

def test_informe_get_autenticado(client_autenticado):
    """GET /informe con sesión debe devolver 200."""
    r = client_autenticado.get("/informe")
    assert r.status_code == 200


def test_informe_ver_sin_datos_redirige(client_autenticado):
    """GET /informe/ver sin informe guardado debe redirigir a /informe."""
    r = client_autenticado.get("/informe/ver")
    assert r.status_code == 302


def test_programar_get_autenticado(client_autenticado):
    """GET /programar con sesión debe devolver 200."""
    r = client_autenticado.get("/programar")
    assert r.status_code == 200


# ─── Tests: conexión con token (API mockeada) ─────────────────────────────────

def test_index_post_token_valido(client):
    """POST / con token válido: la API devuelve proyectos y se construye el árbol."""
    proyectos_mock = {
        "_embedded": {
            "elements": [
                {"id": 1, "name": "Proyecto Test", "_links": {"parent": {}}}
            ]
        }
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = proyectos_mock
    mock_resp.raise_for_status.return_value = None

    with patch("requests.get", return_value=mock_resp):
        r = client.post("/", data={"token": "token_valido"})

    assert r.status_code == 200
    assert b"Proyecto Test" in r.data


def test_index_post_token_invalido(client):
    """POST / con token inválido: la API falla y se muestra error."""
    import requests as req
    with patch("requests.get", side_effect=req.exceptions.ConnectionError("fallo")):
        r = client.post("/", data={"token": "token_malo"})

    assert r.status_code == 200
    assert "error" in r.data.decode().lower()


def test_miembros_con_sesion(client_autenticado):
    """GET /proyecto/<id>/miembros debe devolver JSON con jefes y directores."""
    miembros_mock = {
        "_embedded": {
            "elements": [
                {
                    "_links": {
                        "roles":     [{"title": "Jefe de proyecto"}],
                        "principal": {"title": "Ana García", "href": "/api/v3/users/1"}
                    }
                }
            ]
        }
    }
    usuario_mock = {"name": "Ana García", "email": "ana@example.com"}

    def fake_api(path, params=None):
        if "memberships" in path:
            return miembros_mock
        if "users" in path:
            return usuario_mock
        return None

    with patch("app.api_get", side_effect=fake_api):
        r = client_autenticado.get("/proyecto/1/miembros")

    assert r.status_code == 200
    data = r.get_json()
    assert len(data["jefes"]) == 1
    assert data["jefes"][0]["nombre"] == "Ana García"
    assert data["directores"] == []
