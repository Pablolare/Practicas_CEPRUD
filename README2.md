# OpenProject

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

## Fases de desarrollo previstas

### Fase 1 – Conexión básica y listado de proyectos visibles
- Solicitar token API de OpenProject mediante un formulario / cuadro de diálogo.
- Autenticarse con el token (Basic Auth: `apikey:token`).
- Obtener y mostrar la lista de **proyectos visibles** para el usuario autenticado (`/api/v3/projects`).
- Mostrar información básica: nombre, identifier, ID, estado activo/público.
- **Sin persistencia** del token (solo en memoria de sesión).

**Tecnologías iniciales**: Flask (Python), Jinja2, Requests, HTML/CSS básico.

### Fase 2 – Clasificación de proyectos (Árbol + Roles)
- Mostrar la estructura jerárquica de proyectos (árbol padre-hijo).
- Permitir al administrador marcar proyectos como:
  - **Servicio** → identificar automáticamente al **jefe de proyecto** (responsable asignado).
  - **Área** → identificar a las personas con rol **Director técnico**.
- Mostrar nombre y correo electrónico de los responsables identificados.
- Guardar la clasificación (probablemente en una base de datos ligera o archivo JSON por ahora).

### Fase 3 – Generación de informes agregados
- Seleccionar uno o varios **Servicios** (proyectos marcados en fase 2).
- Parámetros del informe:
  - Rango de fechas (número de días hacia atrás o fechas concretas).
  - Nivel de detalle: solo agregado por persona/servicio o también desglosado por **paquete de trabajo** (work package).
- Obtener las **time entries** (`/api/v3/time_entries`) filtradas por:
  - Proyecto(s) seleccionado(s)
  - Miembros del proyecto
  - Rango de fechas
- Generar informe visual (HTML o PDF simple) con:
  - Horas totales por persona
  - Horas por paquete de trabajo (si se selecciona detalle)
  - Agrupación por servicio/área

### Fase 4 – Envío programado por email
- Programar tareas periódicas (ej: semanal, mensual) para generar y enviar informes.
- Enviar email a cada responsable (jefe de servicio / director técnico) con su informe correspondiente.
- Posibles tecnologías:
  - Celery + Redis / RQ para tareas asíncronas y programadas
  - SMTP (o servicio como SendGrid, Mailgun, etc.)
- Configuración segura de credenciales de email (variables de entorno).

## Tecnologías previstas

- Backend: **Flask** (Python)
- Frontend: HTML + Jinja2
- HTTP: **requests**
- Almacenamiento temporal/config: JSON
- Entorno: **venv** + **requirements.txt**
- Control de versiones: **Git + GitHub**

## Instalación y ejecución (Fase 1)

```bash
# Clonar el repositorio
git clone https://github.com/tu-usuario/openproject-horas-reporter.git
cd openproject-horas-reporter

# Crear y activar entorno virtual
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# Instalar dependencias
pip install -r requirements.txt

# Ejecutar la aplicación
flask run
# o
python app.py
