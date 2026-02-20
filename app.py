from flask import Flask, render_template, request, flash, redirect, url_for, session
import requests
import base64

app = Flask(__name__)
app.secret_key = "secret_key" # Cambia esto por una clave secreta real

BASE_URL = "https://ofiwebsubdir.ugr.es"

def get_auth_header(token):
    """"Genera el header Basic Auth para OpenProject API token"""
    if not token:
        return None
    auth_str = f"apikey:{token}"
    b64_auth = base64.b64encode(auth_str.encode('utf-8')).decode('utf-8')
    return {
        "Authorization": f"Basic {b64_auth}",
        "Accept": "application/hal+json"
    }

@app.route('/', methods =['GET', 'POST'])
def index():
    projects = []
    error = None
    
    if request.method == 'POST':
        token = request.form.get('token','').strip()
        if not token:
            error = "Por favor, ingresa un token de API válido."
        else:
            session['op_token'] = token

            headers = get_auth_header(token)
            try:
                response = requests.get(f"{BASE_URL}/api/v3/projects", 
                                        headers=headers,
                                        timeout=10
                                        )
                response.raise_for_status() # Lanza error si noes 200 OK

                data = response.json()
                projects = data.get('_embedded', {}).get('elements', [])
            
                if not projects:
                    flash("Conexion OK, pero no tienes proyectos visibles.", "info")

            except requests.exceptions.RequestException as e:
                error = f"Error al conectar con OpenProject: {str(e)}"
                session.pop('op_token', None) # Elimina token inválido
            
    return render_template('index.html', projects=projects, error=error)

@app.route('/logout')
def logout():
    session.pop('op_token', None)
    flash("Sesión cerrada. Introduce el token de nuevo si quieres reconectar.", "info")
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)