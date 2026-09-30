# Proyecto SO - Monitor de Procesamiento de Imágenes

## Requisitos
- Python 3.10+
- Flask (`pip install flask`)

## Ejecución
```bash
cd Backend
python app.py
```

El servidor inicia en `http://127.0.0.1:5000`

## Verificación manual de rutas

### 1. Dashboard web (GET /)
Abrir en el navegador:
```
http://127.0.0.1:5000/
```
Muestra el panel con 3 tarjetas (Recibidos, Pendientes, Procesados) y dos botones:
- **Iniciar (Sincronizado)** — procesamiento correcto con locks
- **Iniciar (Con Bug de Concurrencia)** — race condition intencional

### 2. Iniciar procesamiento (POST /start)
Desde terminal (PowerShell):
```powershell
# Modo sincronizado (correcto)
Invoke-WebRequest -Uri "http://127.0.0.1:5000/start" -Method POST -Body '{"bug": false}' -ContentType "application/json"

# Modo con race condition (bug)
Invoke-WebRequest -Uri "http://127.0.0.1:5000/start" -Method POST -Body '{"bug": true}' -ContentType "application/json"
```
Respuesta esperada: `{"status":"started","bug":false}` (o 400 si ya hay uno corriendo)

### 3. Ver estadísticas (GET /stats)
Desde terminal o navegador:
```
http://127.0.0.1:5000/stats
```
Respuesta JSON en tiempo real:
```json
{"received": 50, "processed": 12, "pending": 38, "running": true, "total": 100}
```

### Flujo completo de prueba
1. Abrir `http://127.0.0.1:5000/` en el navegador
2. Click en **"Iniciar (Sincronizado)"**
3. Observar cómo suben **Recibidos** y **Pendientes**, luego bajan **Pendientes** y suben **Procesados**
4. Al terminar, muestra mensaje verde **ÉXITO** (100/100)
5. Repetir con **"Iniciar (Con Bug de Concurrencia)"** → mensaje rojo **FALLO DETECTADO** (procesados < 100)

## Rutas API
- `GET /` — Dashboard HTML
- `POST /start` — Inicia job (`{"bug": false|true}`)
- `GET /stats` — Estado actual en JSON