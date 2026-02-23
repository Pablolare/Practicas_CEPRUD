from flask import Flask, render_template, request, flash, redirect, url_for, session, jsonify
import requests
import base64
import json
import os

app = Flask(__name__)
app.secret_key = "secret_key"

BASE_URL           = "https://ofiwebsubdir.ugr.es"
ROL_JEFE_SERVICIO  = "Jefe de proyecto"
ROL_DIRECTOR_AREA  = "Director técnico"
CLASIFICACION_FILE = "clasificacion.json"


# ─── Helpers: autenticación ───────────────────────────────────────────────────

def get_auth_header(token):
    """Genera el header Basic Auth para la API de OpenProject."""
    if not token:
        return None
    auth_str = f"apikey:{token}"
    b64_auth = base64.b64encode(auth_str.encode("utf-8")).decode("utf-8")
    return {
        "Authorization": f"Basic {b64_auth}",
        "Accept": "application/hal+json"
    }


def api_get(path, params=None):
    """GET autenticado a la API usando el token guardado en sesión."""
    token = session.get("op_token")
    if not token:
        return None
    try:
        r = requests.get(
            f"{BASE_URL}{path}",
            headers=get_auth_header(token),
            params=params,
            timeout=10
        )
        r.raise_for_status()
        return r.json()
    except requests.exceptions.RequestException:
        return None


# ─── Helpers: proyectos ───────────────────────────────────────────────────────

def obtener_miembros(proyecto_id):
    """Devuelve todos los miembros de un proyecto con sus roles."""
    filtros = json.dumps([
        {"project": {"operator": "=", "values": [str(proyecto_id)]}}
    ])
    data = api_get("/api/v3/memberships", params={"filters": filtros})
    if data:
        return data.get("_embedded", {}).get("elements", [])
    return []


def obtener_usuario(user_href):
    """Devuelve nombre y email de un usuario a partir de su href."""
    data = api_get(user_href)
    if data:
        return {
            "nombre": data.get("name", ""),
            "email":  data.get("email", "")
        }
    return None


def construir_arbol(projects):
    """
    Convierte la lista plana de proyectos en árbol padre-hijo.
    Usa _links.parent.href de cada proyecto para enlazarlo con su padre.
    """
    por_id = {str(p["id"]): p for p in projects}
    for p in projects:
        p["children"] = []

    raices = []
    for p in projects:
        parent_href = p.get("_links", {}).get("parent", {}).get("href")
        if parent_href:
            parent_id = parent_href.rstrip("/").split("/")[-1]
            padre = por_id.get(parent_id)
            if padre:
                padre["children"].append(p)
            else:
                raices.append(p)
        else:
            raices.append(p)
    return raices


# ─── Helpers: JSON local ──────────────────────────────────────────────────────

def cargar_clasificacion():
    """Lee clasificacion.json. Devuelve {} si no existe."""
    if os.path.exists(CLASIFICACION_FILE):
        with open(CLASIFICACION_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def guardar_clasificacion(datos):
    """Guarda el diccionario de clasificación en clasificacion.json."""
    with open(CLASIFICACION_FILE, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


# ─── FASE 1: Conexión ─────────────────────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def index():
    arbol         = []
    clasificacion = {}
    error         = None

    if request.method == "POST":
        token = request.form.get("token", "").strip()
        if not token:
            error = "Por favor, ingresa un token de API válido."
        else:
            session["op_token"] = token
            try:
                response = requests.get(
                    f"{BASE_URL}/api/v3/projects",
                    headers=get_auth_header(token),
                    timeout=10
                )
                response.raise_for_status()
                projects = response.json().get("_embedded", {}).get("elements", [])
                if not projects:
                    flash("Conexión OK, pero no tienes proyectos visibles.", "info")
                else:
                    arbol         = construir_arbol(projects)
                    clasificacion = cargar_clasificacion()
            except requests.exceptions.RequestException as e:
                error = f"Error al conectar con OpenProject: {str(e)}"
                session.pop("op_token", None)

    return render_template("index.html", arbol=arbol, error=error,
                           clasificacion=clasificacion)


@app.route("/logout")
def logout():
    session.pop("op_token", None)
    flash("Sesión cerrada. Introduce el token de nuevo si quieres reconectar.", "info")
    return redirect(url_for("index"))


# ─── FASE 2: Miembros y clasificación (llamadas AJAX) ─────────────────────────

@app.route("/proyecto/<int:proyecto_id>/miembros")
def proyecto_miembros(proyecto_id):
    """Devuelve en JSON los jefes y directores del proyecto."""
    if not session.get("op_token"):
        return jsonify({"error": "No autenticado"}), 401

    jefes      = []
    directores = []

    for miembro in obtener_miembros(proyecto_id):
        roles     = [r.get("title", "") for r in miembro.get("_links", {}).get("roles", [])]
        nombre    = miembro.get("_links", {}).get("principal", {}).get("title", "")
        user_href = miembro.get("_links", {}).get("principal", {}).get("href", "")

        usuario = obtener_usuario(user_href) if user_href else None
        email   = usuario["email"] if usuario else ""

        if ROL_JEFE_SERVICIO in roles:
            jefes.append({"nombre": nombre, "email": email})
        if ROL_DIRECTOR_AREA in roles:
            directores.append({"nombre": nombre, "email": email})

    return jsonify({"jefes": jefes, "directores": directores})


@app.route("/proyecto/<int:proyecto_id>/clasificar", methods=["POST"])
def clasificar_proyecto(proyecto_id):
    """Guarda la clasificación (servicio/area/ninguno) de un proyecto."""
    if not session.get("op_token"):
        return jsonify({"error": "No autenticado"}), 401

    datos  = request.get_json()
    tipo   = datos.get("tipo")
    nombre = datos.get("nombre", "")

    clasificacion = cargar_clasificacion()

    if tipo == "ninguno":
        clasificacion.pop(str(proyecto_id), None)
    else:
        clasificacion[str(proyecto_id)] = {
            "tipo":            tipo,
            "nombre_proyecto": nombre
        }

    guardar_clasificacion(clasificacion)
    return jsonify({"ok": True, "tipo": tipo})


if __name__ == "__main__":
    app.run(debug=True)
