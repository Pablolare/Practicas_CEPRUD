# OpenProject Reporter

Pequeña aplicación web para generar y enviar informes automáticos de horas registradas en **OpenProject** a jefes de proyecto / responsables de servicio y directores técnicos.

## Descripción del proyecto

La herramienta permite a un administrador:

- Conectar a una instancia de OpenProject mediante un token API (solo lectura).
- Identificar proyectos de tipo **Servicio** y **Área**.
- Extraer automáticamente los responsables (jefes de proyecto / directores técnicos).
- Generar informes agregados de horas trabajadas por los miembros de los equipos.
- Enviar estos informes de forma programada por correo electrónico.

**Importante**: La aplicación **no realiza modificaciones** en OpenProject. Solo lee datos (proyectos, miembros, paquetes de trabajo, time entries).  
Los permisos y visibilidad dependen exclusivamente del usuario cuyo token se utilice.

## Fases de desarrollo

### Fase 1 – Conexión básica y listado de proyectos visibles ✅

- Solicitar token API de OpenProject mediante un formulario / cuadro de diálogo.
- Autenticarse con el token (Basic Auth: `apikey:token`).
- Obtener y mostrar la lista de **proyectos visibles** para el usuario autenticado (`/api/v3/projects`).
- Mostrar información básica: nombre, identifier, ID, estado activo/público.
- **Sin persistencia** del token (solo en memoria de sesión).

**Tecnologías**: Flask (Python), Jinja2, Requests, HTML/CSS.

### Fase 2 – Clasificación de proyectos (Árbol + Roles) ✅

- Mostrar la estructura jerárquica de proyectos (árbol padre-hijo).
- Permitir al administrador marcar proyectos como:
  - **Servicio** → identificar automáticamente al **jefe de proyecto** (responsable asignado).
  - **Área** → identificar a las personas con rol **Director técnico**.
- Mostrar nombre y correo electrónico de los responsables identificados.

### Fase 3 – Generación de informes agregados ✅

- Seleccionar uno o varios **Servicios** (proyectos marcados en fase 2).
- Parámetros del informe:
  - Rango de fechas (número de días hacia atrás o fechas concretas).
  - Nivel de detalle: solo agregado por persona/servicio o también desglosado por **paquete de trabajo** (work package).
- Obtener las **time entries** (`/api/v3/time_entries`) filtradas por proyecto(s), miembros y rango de fechas.
- Generar informe visual en HTML con horas totales por persona y agrupación por servicio/área.

### Fase 4 – Envío programado por email ✅

- Programar tareas periódicas (semanal, mensual) para generar y enviar informes usando **APScheduler**.
- Enviar email a cada responsable (jefe de servicio / director técnico) con su informe correspondiente.
- Configuración de credenciales SMTP desde la propia interfaz (Gmail, Outlook, Yahoo u otro).

## Tecnologías utilizadas

- Backend: **Flask** (Python)
- Servidor WSGI: **Gunicorn**
- Servidor web: **Apache** (reverse proxy)
- Frontend: HTML + CSS + Jinja2
- HTTP: **requests**
- Tareas programadas: **APScheduler**
- Entorno: **venv** + **requirements.txt**
- Control de versiones: **Git + GitHub**

## Instalación y ejecución en local

```bash
# Clonar el repositorio
git clone https://github.com/tu-usuario/openproject-horas-reporter.git
cd openproject-horas-reporter

# Crear y activar entorno virtual
python -m venv .venv
source .venv/bin/activate          # Windows (PowerShell): .venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt

# Ejecutar la aplicación en local
$env:SCRIPT_NAME="/ceprud"; flask run   # Windows (PowerShell)
SCRIPT_NAME=/ceprud flask run           # Linux/Mac
```

La aplicación estará disponible en `http://127.0.0.1:5000/ceprud/`.

## Despliegue en producción (Apache + Gunicorn)

### Primera vez

Conéctate por SSH al servidor y clona el repositorio:

```bash
git clone https://github.com/tu-usuario/openproject-horas-reporter.git
cd openproject-horas-reporter
```

Crea el entorno virtual e instala las dependencias:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install gunicorn
```

### Arrancar Gunicorn

**Importante**: Gunicorn debe estar corriendo antes de que Apache pueda redirigir el tráfico a la aplicación.

```bash
nohup gunicorn -w 4 -b 127.0.0.1:5000 --env SCRIPT_NAME=/ceprud app:app &
```

- `nohup` hace que el proceso siga corriendo aunque cierres la sesión SSH
- `-w 4` arranca 4 workers para manejar peticiones en paralelo
- `-b 127.0.0.1:5000` escucha solo en localhost, no expuesto al exterior
- `--env SCRIPT_NAME=/ceprud` indica a Flask que la app está en el subdirectorio `/ceprud/`
- `&` deja el proceso corriendo en segundo plano

Para verificar que está corriendo correctamente:

```bash
curl http://127.0.0.1:5000/ceprud/
```

### Configurar Apache (reverse proxy)

Añadir en el archivo de configuración de Apache (antes del `ProxyPass /` general):

```apache
ProxyPass /ceprud/ http://127.0.0.1:5000/ceprud/
ProxyPassReverse /ceprud/ http://127.0.0.1:5000/ceprud/
```

### Reiniciar Apache

```bash
sudo systemctl restart apache2
```

La aplicación estará disponible en `https://ofiwebsubdir.ugr.es/ceprud/`.

## Actualizar el proyecto en producción

Para subir cambios al servidor, conéctate por SSH y ejecuta:

```bash
cd /home/tu_usuario/Practicas_CEPRUD
git pull
pkill gunicorn
nohup gunicorn -w 4 -b 127.0.0.1:5000 --env SCRIPT_NAME=/ceprud app:app &
```

### Notas importantes

- Si el servidor se reinicia, Gunicorn se detendrá y habrá que arrancarlo de nuevo manualmente. La automatización de este arranque mediante `systemd` está pendiente de configurar.
- Para detener Gunicorn manualmente: `pkill gunicorn`
