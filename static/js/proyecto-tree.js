const cargados = {};
const datosPorId = {};  // guarda grupos por proyecto tras la primera carga

    // Aplica sangría según data-nivel
    document.querySelectorAll('.proyecto-item').forEach(item => {
        const nivel = parseInt(item.dataset.nivel) || 0;
        item.style.paddingLeft = (nivel * 20) + 'px';
    });

    // Asigna el click a cada fila
    document.querySelectorAll('.proyecto-fila').forEach(fila => {
        fila.addEventListener('click', function () {
            togglePanel(this.dataset.id);
        });
    });

    function togglePanel(id) {
        const panel = document.getElementById('panel-' + id);
        const fila  = panel.previousElementSibling;
        
        if (panel.classList.contains('abierto')) {
            panel.classList.remove('abierto');
            fila.querySelector('.proyecto-icono').textContent = '▶';
            return;
        }

        panel.classList.add('abierto');
        fila.querySelector('.proyecto-icono').textContent = '▼';

        if (cargados[id]) return;

        panel.innerHTML = '<div class="cargando">Cargando...</div>';

        fetch('/proyecto/' + id + '/miembros')
            .then(r => r.json())
            .then(data => {
                datosPorId[id] = data;

                const html = `
                    <div class="clasificacion-grupo">
                        <span class="clasificacion-label">Ver</span>
                        <div class="clasificacion-segmento">
                            <button class="btn-clasificar" data-id="${id}" data-tipo="servicio">Servicio</button>
                            <button class="btn-clasificar" data-id="${id}" data-tipo="area">Área</button>
                        </div>
                    </div>
                    <div class="miembros-resultado" id="resultado-${id}"></div>
                `;

                panel.innerHTML = '<div class="miembros-panel">' + html + '</div>';
                cargados[id] = true;
            })
            .catch(() => {
                panel.innerHTML = '<p class="sin-responsables">Error al cargar los miembros.</p>';
            });
    }

    // Click en los botones Servicio / Área
    document.addEventListener('click', function (e) {
        const btn = e.target.closest('.btn-clasificar');
        if (!btn) return;

        const id   = btn.dataset.id;
        const tipo = btn.dataset.tipo;
        const data = datosPorId[id];
        if (!data) return;

        // Marca el botón activo
        const panel = document.getElementById('panel-' + id);
        panel.querySelectorAll('.btn-clasificar').forEach(b => {
            b.classList.toggle('activo', b === btn);
        });

        // Actualiza el badge
        const badge = document.getElementById('badge-' + id);
        if (badge) {
            badge.className   = 'badge badge-' + tipo;
            badge.textContent = tipo === 'servicio' ? 'Servicio' : 'Área';
        }

        // Muestra el grupo correspondiente
        const personas = tipo === 'servicio' ? data.jefes : data.directores;
        const titulo   = tipo === 'servicio' ? 'Jefes de proyecto' : 'Directores técnicos';
        const claseRol = tipo === 'servicio' ? 'rol-servicio' : 'rol-area';
        const resultado = document.getElementById('resultado-' + id);

        if (!personas.length) {
            resultado.innerHTML = '<p class="sin-responsables">No hay responsables asignados para este tipo.</p>';
            return;
        }

        let html = `<div class="rol-grupo"><span class="rol-titulo ${claseRol}">${titulo}</span>`;
        personas.forEach(p => {
            html += `<div class="persona-item">
                <span class="persona-nombre">${p.nombre}</span>
                ${p.email ? `<span class="persona-email">${p.email}</span>` : ''}
            </div>`;
        });
        html += '</div>';

        resultado.innerHTML = html;
    });