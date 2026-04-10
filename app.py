from flask import Flask, render_template, request, flash, redirect, url_for, session, jsonify
import requests
import base64
import json
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
app.secret_key = "secret_key"

BASE_URL          = "https://ofiwebsubdir.ugr.es"
ROL_JEFE_SERVICIO = "Jefe de proyecto"
ROL_DIRECTOR_AREA = "Director tecnico"

# ─── Estado global del scheduler ──────────────────────────────────────────────
# El token no está disponible en tareas en background (sin sesión Flask),
# por eso lo guardamos en memoria cuando el usuario hace login.
_op_token_global   = None
_config_email      = {}   # smtp_host, smtp_port, smtp_user, smtp_pass, dias
_scheduler         = BackgroundScheduler()
_scheduler.start()


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


# ─── Helpers: árbol desde sesión ──────────────────────────────────────────────

def obtener_ids_descendientes(proyecto_id, proyectos):
    """Devuelve lista con el ID del proyecto y todos sus subproyectos recursivamente."""
    ids = [proyecto_id]
    for p in proyectos:
        if p["parent_id"] == proyecto_id:
            ids.extend(obtener_ids_descendientes(p["id"], proyectos))
    return ids


def construir_arbol_sesion(proyectos):
    """Construye árbol padre-hijo a partir de la lista de sesión {id, name, parent_id}."""
    por_id = {p["id"]: dict(p, children=[]) for p in proyectos}
    raices = []
    for p in por_id.values():
        pid = p.get("parent_id")
        if pid and pid in por_id:
            por_id[pid]["children"].append(p)
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
    error = None

    # Si ya hay sesión activa, reconstruimos el árbol desde los datos guardados
    if request.method == "GET" and session.get("op_token") and session.get("proyectos"):
        arbol = construir_arbol_sesion(session["proyectos"])
        return render_template("index.html", arbol=arbol, error=error)

    arbol = []

    if request.method == "POST":
        token = request.form.get("token", "").strip()
        if not token:
            error = "Por favor, ingresa un token de API válido."
        else:
            global _op_token_global
            session["op_token"]  = token
            _op_token_global     = token   # disponible para tareas en background
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
                        {
                            "id":        p["id"],
                            "name":      p["name"],
                            "parent_id": int(p["_links"]["parent"]["href"].split("/")[-1])
                                         if p.get("_links", {}).get("parent", {}).get("href")
                                         else None
                        }
                        for p in projects
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


@app.route("/informe/<int:proyecto_id>", methods=["GET", "POST"])
def informe_proyecto(proyecto_id):
    """Genera el informe de horas de un proyecto y todos sus subproyectos."""
    if not session.get("op_token"):
        return redirect(url_for("index"))

    proyectos = session.get("proyectos", [])
    proyecto_raiz = next((p for p in proyectos if p["id"] == proyecto_id), None)
    if not proyecto_raiz:
        return redirect(url_for("index"))

    resultado         = None
    personas_ordenadas = []
    totales_persona   = {}
    dias              = ""

    if request.method == "POST":
        dias_raw = request.form.get("dias", "").strip()
        dias     = int(dias_raw) if dias_raw else None

        if dias:
            fecha_desde       = (datetime.today() - timedelta(days=dias)).strftime("%Y-%m-%d")
            fecha_desde_label = (datetime.today() - timedelta(days=dias)).strftime("%d/%m/%Y")
        else:
            fecha_desde       = None
            fecha_desde_label = "el inicio"

        # IDs del proyecto raíz + todos sus subproyectos
        ids          = obtener_ids_descendientes(proyecto_id, proyectos)
        nombre_por_id = {p["id"]: p["name"] for p in proyectos}

        resultado      = {}
        todas_personas = set()

        for pid in ids:
            entries = obtener_time_entries(pid, fecha_desde)
            if not entries:
                continue
            nombre   = nombre_por_id.get(pid, str(pid))
            personas = {}
            for entry in entries:
                persona = entry.get("_links", {}).get("user", {}).get("title", "Desconocido")
                horas   = parse_horas(entry.get("hours", 0))
                personas[persona] = personas.get(persona, 0.0) + horas
                todas_personas.add(persona)
            resultado[nombre] = {
                "personas": personas,
                "total":    sum(personas.values())
            }

        personas_ordenadas = sorted(todas_personas)
        totales_persona    = {
            p: sum(datos["personas"].get(p, 0.0) for datos in resultado.values())
            for p in personas_ordenadas
        }

        session["ultimo_informe"] = {
            "resultado":          resultado,
            "personas_ordenadas": personas_ordenadas,
            "totales_persona":    totales_persona,
            "dias":               dias,
            "fecha_desde":        fecha_desde_label,
            "proyecto_nombre":    proyecto_raiz["name"]
        }

    return render_template("informe.html",
                           resultado=resultado,
                           personas_ordenadas=personas_ordenadas,
                           totales_persona=totales_persona,
                           dias=dias,
                           proyecto_nombre=proyecto_raiz["name"],
                           proyecto_id=proyecto_id)


@app.route("/informe/ver")
def informe_ver():
    """Muestra el informe en formato imprimible (nueva pestaña)."""
    if not session.get("op_token"):
        return redirect(url_for("index"))

    datos = session.get("ultimo_informe")
    if not datos:
        return redirect(url_for("informe"))

    return render_template("informe_ver.html", **datos)


# ─── FASE 4: Programar envío de informes por email ────────────────────────────

def generar_informe_datos(token, dias=None):
    """Genera el dict de resultado igual que la ruta /informe, usando un token dado."""
    proyectos = []
    try:
        resp = requests.get(
            f"{BASE_URL}/api/v3/projects",
            headers=get_auth_header(token),
            timeout=10
        )
        resp.raise_for_status()
        proyectos = [
            {"id": str(p["id"]), "name": p["name"]}
            for p in resp.json().get("_embedded", {}).get("elements", [])
        ]
    except Exception:
        return {}

    if dias:
        fecha_desde = (datetime.today() - timedelta(days=dias)).strftime("%Y-%m-%d")
    else:
        fecha_desde = None

    resultado = {}
    for proyecto in proyectos:
        entries = obtener_time_entries(proyecto["id"], fecha_desde)
        if not entries:
            continue
        personas = {}
        for entry in entries:
            persona = entry.get("_links", {}).get("user", {}).get("title", "Desconocido")
            horas   = parse_horas(entry.get("hours", 0))
            if persona not in personas:
                personas[persona] = 0.0
            personas[persona] += horas
        resultado[proyecto["name"]] = {
            "personas": {p: {"total": h, "paquetes": {}} for p, h in personas.items()},
            "total":    sum(personas.values())
        }
    return resultado


def construir_html_email(resultado, dias):
    """Construye el cuerpo HTML del correo con el informe de horas."""
    periodo = f"Últimos {dias} días" if dias else "Todo el historial"
    fecha   = datetime.today().strftime("%d/%m/%Y")

    filas = ""
    for nombre_proyecto, datos in resultado.items():
        filas += f"""
        <tr style="background:#e8eaf6">
            <td colspan="2" style="padding:8px 12px;font-weight:700;color:#3730a3">
                {nombre_proyecto}
                <span style="float:right;font-size:0.85rem;color:#6366f1">
                    {datos['total']:.1f} h total
                </span>
            </td>
        </tr>"""
        for persona, info in datos["personas"].items():
            filas += f"""
        <tr>
            <td style="padding:6px 12px 6px 24px;color:#374151">{persona}</td>
            <td style="padding:6px 12px;text-align:right;font-weight:600">{info['total']:.1f} h</td>
        </tr>"""

    return f"""
    <html><body style="font-family:sans-serif;color:#1e1b4b;max-width:640px;margin:auto">
        <h2 style="color:#3730a3">Informe de horas – OpenProject</h2>
        <p style="color:#6b7280">{periodo} · Generado el {fecha}</p>
        <table width="100%" cellspacing="0" cellpadding="0"
               style="border-collapse:collapse;border:1px solid #e0e7ff;border-radius:8px;overflow:hidden">
            <thead>
                <tr style="background:#3730a3;color:#fff">
                    <th style="padding:10px 12px;text-align:left">Persona</th>
                    <th style="padding:10px 12px;text-align:right">Horas</th>
                </tr>
            </thead>
            <tbody>{filas}</tbody>
        </table>
        <p style="color:#9ca3af;font-size:0.8rem;margin-top:24px">
            Enviado automáticamente por OpenProject Reporter
        </p>
    </body></html>
    """


def enviar_email(destinatarios, asunto, html):
    """Envía un correo HTML a la lista de destinatarios usando la config guardada."""
    cfg = _config_email
    if not cfg or not destinatarios:
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = asunto
        msg["From"]    = cfg["smtp_user"]
        msg["To"]      = ", ".join(destinatarios)
        msg.attach(MIMEText(html, "html", "utf-8"))

        with smtplib.SMTP(cfg["smtp_host"], int(cfg["smtp_port"]), timeout=15) as srv:
            srv.ehlo()
            srv.starttls()
            srv.login(cfg["smtp_user"], cfg["smtp_pass"])
            srv.sendmail(cfg["smtp_user"], destinatarios, msg.as_string())
        return True
    except Exception as e:
        app.logger.error(f"Error enviando email: {e}")
        return False


def enviar_informe_programado():
    """Tarea ejecutada por APScheduler: genera el informe y lo envía por email."""
    token = _op_token_global
    if not token:
        app.logger.warning("Scheduler: no hay token guardado, se omite el envío.")
        return

    dias      = _config_email.get("dias")
    resultado = generar_informe_datos(token, dias)
    if not resultado:
        app.logger.info("Scheduler: informe vacío, no se envía.")
        return

    # Recopila emails de jefes y directores, filtrando por proyectos seleccionados
    sel           = set(_config_email.get("proyectos_seleccionados", []))
    destinatarios = set()
    try:
        resp = requests.get(
            f"{BASE_URL}/api/v3/projects",
            headers=get_auth_header(token),
            timeout=10
        )
        resp.raise_for_status()
        proyectos = resp.json().get("_embedded", {}).get("elements", [])
        for p in proyectos:
            if sel and p["id"] not in sel:
                continue
            for miembro in obtener_miembros(p["id"]):
                roles     = [r.get("title", "") for r in miembro.get("_links", {}).get("roles", [])]
                user_href = miembro.get("_links", {}).get("principal", {}).get("href", "")
                if ROL_JEFE_SERVICIO in roles or ROL_DIRECTOR_AREA in roles:
                    usuario = obtener_usuario(user_href) if user_href else None
                    if usuario and usuario.get("email"):
                        destinatarios.add(usuario["email"])
    except Exception as e:
        app.logger.error(f"Scheduler: error obteniendo destinatarios: {e}")
        return

    if not destinatarios:
        app.logger.info("Scheduler: no se encontraron destinatarios.")
        return

    html  = construir_html_email(resultado, dias)
    fecha = datetime.today().strftime("%d/%m/%Y")
    ok    = enviar_email(list(destinatarios), f"Informe de horas – {fecha}", html)
    app.logger.info(f"Scheduler: informe enviado a {len(destinatarios)} destinatarios. OK={ok}")


@app.route("/programar", methods=["GET", "POST"])
def programar():
    if not session.get("op_token"):
        return redirect(url_for("index"))

    global _config_email
    mensaje = None

    if request.method == "POST":
        accion = request.form.get("accion")

        if accion == "guardar":
            ids_raw = request.form.getlist("proyectos_sel")
            _config_email = {
                "smtp_host":              request.form.get("smtp_host", "").strip(),
                "smtp_port":              request.form.get("smtp_port", "587").strip(),
                "smtp_user":              request.form.get("smtp_user", "").strip(),
                "smtp_pass":              request.form.get("smtp_pass", "").strip(),
                "dias":                   int(request.form.get("dias")) if request.form.get("dias", "").strip() else None,
                "proyectos_seleccionados": [int(i) for i in ids_raw] if ids_raw else [],
            }
            frecuencia = int(request.form.get("frecuencia", 7))
            # Elimina job anterior si existe y crea el nuevo
            if _scheduler.get_job("informe_email"):
                _scheduler.remove_job("informe_email")
            _scheduler.add_job(
                enviar_informe_programado,
                trigger="interval",
                days=frecuencia,
                id="informe_email",
                replace_existing=True
            )
            mensaje = f"Configuración guardada. Se enviará cada {frecuencia} día(s)."

        elif accion == "enviar_ahora":
            if not _config_email:
                mensaje = "Primero guarda la configuración SMTP."
            else:
                enviar_informe_programado()
                mensaje = "Informe enviado manualmente."

        elif accion == "desactivar":
            if _scheduler.get_job("informe_email"):
                _scheduler.remove_job("informe_email")
            mensaje = "Envío automático desactivado."

    job        = _scheduler.get_job("informe_email")
    proximo    = job.next_run_time.strftime("%d/%m/%Y %H:%M") if job and job.next_run_time else None
    config_act = _config_email.copy()
    config_act.pop("smtp_pass", None)   # no enviar la contraseña al template

    arbol_proyectos = construir_arbol_sesion(session.get("proyectos", []))
    seleccionados   = set(_config_email.get("proyectos_seleccionados", []))

    return render_template("programar.html",
                           mensaje=mensaje,
                           proximo=proximo,
                           config=config_act,
                           arbol=arbol_proyectos,
                           seleccionados=seleccionados)


if __name__ == "__main__":
    app.run(debug=True)
