"""
MCP Server – OpenProject Reporter
Herramienta: filtrar paquetes de trabajo por usuario, ordenados por horas.

Instalación:
    pip install mcp

Uso en Claude Desktop (claude_desktop_config.json):
    {
        "mcpServers": {
            "openproject": {
                "command": "python",
                "args": ["ruta/a/mcp_openproject.py"]
            }
        }
    }
"""

import re
import json
import base64
import requests
from datetime import datetime, timedelta
from mcp.server.fastmcp import FastMCP

# ─── Configuración ────────────────────────────────────────────────────────────

BASE_URL = "https://ofiwebsubdir.ugr.es"

mcp = FastMCP("OpenProject Reporter")


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _auth_header(token: str) -> dict:
    """Genera el header Basic Auth con el token de API."""
    b64 = base64.b64encode(f"apikey:{token}".encode()).decode()
    return {"Authorization": f"Basic {b64}", "Accept": "application/hal+json"}


def _parse_horas(valor) -> float:
    """Convierte el valor de horas de la API (float o ISO 8601 'PT2H30M') a float."""
    try:
        return float(valor)
    except (TypeError, ValueError):
        pass
    match = re.match(r'PT(?:(\d+(?:\.\d+)?)H)?(?:(\d+(?:\.\d+)?)M)?', str(valor))
    if match:
        return float(match.group(1) or 0) + float(match.group(2) or 0) / 60
    return 0.0


def _fetch_time_entries(token: str, filtros: str) -> list:
    """Obtiene todos los registros de tiempo paginando de 100 en 100."""
    entries, offset = [], 1
    while True:
        try:
            r = requests.get(
                f"{BASE_URL}/api/v3/time_entries",
                headers=_auth_header(token),
                params={"filters": filtros, "pageSize": 100, "offset": offset},
                timeout=15
            )
            r.raise_for_status()
            data = r.json()
        except requests.exceptions.RequestException as e:
            raise ConnectionError(f"Error al conectar con la API: {e}")

        page = data.get("_embedded", {}).get("elements", [])
        if not page:
            break
        entries.extend(page)
        if len(entries) >= data.get("total", 0):
            break
        offset += 100

    return entries


# ─── Herramienta MCP ──────────────────────────────────────────────────────────

@mcp.tool()
def filtrar_paquetes_por_usuario(
    token: str,
    usuario: str,
    dias: int = None,
    proyecto_id: int = None
) -> str:
    """
    Filtra los paquetes de trabajo de OpenProject por usuario
    y los devuelve ordenados de mayor a menor horas trabajadas.

    Args:
        token:       Token de API de OpenProject.
        usuario:     Nombre (o parte del nombre) del usuario a filtrar.
        dias:        Nº de días hacia atrás a considerar. Sin valor = todo el historial.
        proyecto_id: ID del proyecto a filtrar (opcional). Sin valor = todos los proyectos.
    """
    # Construimos los filtros de la API
    filtro_base = []

    if proyecto_id:
        filtro_base.append({"project": {"operator": "=", "values": [str(proyecto_id)]}})

    if dias:
        fecha_desde = (datetime.today() - timedelta(days=dias)).strftime("%Y-%m-%d")
        fecha_hasta = datetime.today().strftime("%Y-%m-%d")
        filtro_base.append({"spent_on": {"operator": "<>d", "values": [fecha_desde, fecha_hasta]}})

    filtros = json.dumps(filtro_base)

    # Obtenemos los registros de tiempo
    try:
        entries = _fetch_time_entries(token, filtros)
    except ConnectionError as e:
        return str(e)

    if not entries:
        return "No se encontraron registros de tiempo con los filtros aplicados."

    # Filtramos por usuario y agrupamos por paquete de trabajo
    paquetes: dict[str, float] = {}
    for entry in entries:
        nombre_usuario = entry.get("_links", {}).get("user", {}).get("title", "")
        # Búsqueda parcial e insensible a mayúsculas
        if usuario.lower() not in nombre_usuario.lower():
            continue

        paquete = (
            entry.get("_links", {}).get("workPackage", {}).get("title")
            or "Sin paquete de trabajo"
        )
        paquetes[paquete] = paquetes.get(paquete, 0.0) + _parse_horas(entry.get("hours", 0))

    if not paquetes:
        return f"No se encontraron registros para el usuario '{usuario}'."

    # Ordenamos de mayor a menor horas
    ordenados = sorted(paquetes.items(), key=lambda x: x[1], reverse=True)

    # Formateamos la respuesta
    periodo = f"últimos {dias} días" if dias else "todo el historial"
    proyecto_label = f" · Proyecto ID {proyecto_id}" if proyecto_id else ""
    lineas = [
        f"Paquetes de trabajo de '{usuario}' ({periodo}{proyecto_label}):",
        f"{'─' * 50}",
    ]
    for i, (paquete, horas) in enumerate(ordenados, 1):
        lineas.append(f"{i:>2}. {horas:>6.1f} h  –  {paquete}")

    lineas.append(f"{'─' * 50}")
    lineas.append(f"     {sum(paquetes.values()):>6.1f} h  total en {len(paquetes)} paquete(s)")

    return "\n".join(lineas)


# ─── Punto de entrada ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run()
