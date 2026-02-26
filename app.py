from flask import Flask, render_template, request, flash, redirect, url_for, session, jsonify
import requests
import base64
import json
import re
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "secret_key"

BASE_URL          = "https://ofiwebsubdir.ugr.es"
ROL_JEFE_SERVICIO = "Jefe de proyecto"
ROL_DIRECTOR_AREA = "Director técnico"


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


# ─── Helpers: informe ─────────────────────────────────────────────────────────

def parse_horas(valor):
    """Convierte horas de la API (ISO 8601 'PT2H30M' o float) a float."""
    try:
        return float(valor)
    except (TypeError, ValueError):
        pass
    match = re.match(r'PT(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?', str(valor))
    if match:
        return float(match.group(1) or 0) + float(match.group(2) or 0) / 60
    return 0.0


def obtener_time_entries(proyecto_id, fecha_desde=None):
    """Devuelve todas las time entries de un proyecto. Si fecha_desde es None, devuelve todas."""
    filtro_base = [{"project": {"operator": "=", "values": [str(proyecto_id)]}}]
    if fecha_desde:
        fecha_hasta = datetime.today().strftime("%Y-%m-%d")
        filtro_base.append({"spent_on": {"operator": "<>d", "values": [fecha_desde, fecha_hasta]}})
    filtros = json.dumps(filtro_base)
    entries = []
    offset  = 1
    while True:
        data = api_get("/api/v3/time_entries", params={
            "filters":  filtros,
            "pageSize": 100,
            "offset":   offset
        })
        if not data:
            break
        page = data.get("_embedded", {}).get("elements", [])
        if not page:
            break
        entries.extend(page)
        if len(entries) >= data.get("total", 0):
            break
        offset += 100
    return entries


# ─── FASE 1: Conexión ─────────────────────────────────────────────────────────

@app.route("/", methods=["GET", "POST"])
def index():
    arbol = []
    error = None

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
                    arbol = construir_arbol(projects)
                    # Guarda lista plana para usarla en el informe
                    session["proyectos"] = [
                        {"id": p["id"], "name": p["name"]} for p in projects
                    ]
            except requests.exceptions.RequestException as e:
                error = f"Error al conectar con OpenProject: {str(e)}"
                session.pop("op_token", None)

    return render_template("index.html", arbol=arbol, error=error)


@app.route("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada. Introduce el token de nuevo si quieres reconectar.", "info")
    return redirect(url_for("index"))


# ─── FASE 2: Miembros (llamadas AJAX) ─────────────────────────────────────────

@app.route("/proyecto/<int:proyecto_id>/miembros")
def proyecto_miembros(proyecto_id):
    """Devuelve jefes y directores del proyecto desde la API de memberships."""
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


# ─── FASE 3: Informe de horas ─────────────────────────────────────────────────

@app.route("/informe", methods=["GET", "POST"])
def informe():
    if not session.get("op_token"):
        return redirect(url_for("index"))

    resultado   = None
    dias        = ""
    detalle     = False

    if request.method == "POST":
        dias_raw    = request.form.get("dias", "").strip()
        detalle     = "detalle" in request.form
        dias        = int(dias_raw) if dias_raw else None

        if dias:
            fecha_desde  = (datetime.today() - timedelta(days=dias)).strftime("%Y-%m-%d")
            fecha_desde_label = (datetime.today() - timedelta(days=dias)).strftime("%d/%m/%Y")
        else:
            fecha_desde       = None
            fecha_desde_label = "el inicio"

        proyectos = session.get("proyectos", [])
        resultado = {}

        for proyecto in proyectos:
            pid     = str(proyecto["id"])
            entries = obtener_time_entries(pid, fecha_desde)

            if not entries:
                continue

            personas = {}

            for entry in entries:
                persona = entry.get("_links", {}).get("user", {}).get("title", "Desconocido")
                horas   = parse_horas(entry.get("hours", 0))
                paquete = (
                    entry.get("_links", {}).get("workPackage", {}).get("title")
                    or "Sin paquete de trabajo"
                )

                if persona not in personas:
                    personas[persona] = {"total": 0.0, "paquetes": {}}

                personas[persona]["total"] += horas

                if detalle:
                    personas[persona]["paquetes"][paquete] = (
                        personas[persona]["paquetes"].get(paquete, 0.0) + horas
                    )

            resultado[proyecto["name"]] = {
                "personas": personas,
                "total":    sum(p["total"] for p in personas.values())
            }

        session["ultimo_informe"] = {
            "resultado":   resultado,
            "detalle":     detalle,
            "dias":        dias,
            "fecha_desde": fecha_desde_label
        }

    return render_template("informe.html",
                           resultado=resultado,
                           detalle=detalle,
                           dias=dias)


@app.route("/debug/informe")
def debug_informe():
    """Diagnóstico temporal: muestra la respuesta real de la API."""
    if not session.get("op_token"):
        return jsonify({"error": "No autenticado"}), 401

    proyectos = session.get("proyectos", [])
    if not proyectos:
        return jsonify({"error": "Sin proyectos en sesión"})

    fecha_desde = (datetime.today() - timedelta(days=30)).strftime("%Y-%m-%d")
    fecha_hasta = datetime.today().strftime("%Y-%m-%d")
    pid = str(proyectos[0]["id"])
    filtros = json.dumps([
        {"project":  {"operator": "=",   "values": [pid]}},
        {"spent_on": {"operator": "<>d", "values": [fecha_desde, fecha_hasta]}}
    ])

    token = session.get("op_token")
    try:
        r = requests.get(
            f"{BASE_URL}/api/v3/time_entries",
            headers=get_auth_header(token),
            params={"filters": filtros, "pageSize": 5, "offset": 1},
            timeout=10
        )
        try:
            body = r.json()
        except Exception:
            body = r.text[:1000]

        return jsonify({
            "proyectos_en_sesion": len(proyectos),
            "proyecto_probado": proyectos[0]["name"],
            "id_probado": pid,
            "fecha_desde": fecha_desde,
            "filtros_enviados": filtros,
            "status_code": r.status_code,
            "respuesta_api": body
        })
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/informe/ver")
def informe_ver():
    """Muestra el informe en formato imprimible (nueva pestaña)."""
    if not session.get("op_token"):
        return redirect(url_for("index"))

    datos = session.get("ultimo_informe")
    if not datos:
        return redirect(url_for("informe"))

    return render_template("informe_ver.html", **datos)


if __name__ == "__main__":
    app.run(debug=True)
