# Servidor de Procesamiento de Imágenes (Proyecto 2)

Proyecto de Sistemas Operativos – UPTC. Docente: Mgrt. Fredy Antonio Alarcon Fonseca.

Es un servidor que simula el procesamiento de imágenes (miniaturas) usando **procesos, hilos, una cola productor-consumidor y sincronización**. Tiene dos modos de ejecución:

- **Sincronizado:** el contador de trabajos procesados está protegido con un cerrojo (lock) y el resultado es siempre correcto.
- **Con bug de concurrencia:** el contador se actualiza sin protección, para mostrar una **condición de carrera** (se pierden actualizaciones).

El procesamiento de cada imagen es una simulación: gasta CPU con un ciclo de 5 millones de iteraciones y reserva 1 MB de memoria por trabajo para simular que la memoria crece.

## Integrantes

- Edison Gonzalez – 202315046
- Luis Cardenas – 202315164
- Haider Carvajal – 202411800
- Sara Moreno – 202413202

## Estructura del proyecto

```
PROYECTO_SO/
├── README.md
├── Backend/
│   └── app.py                  # Servidor Flask, procesos, hilos y sincronización
└── Frontend/
    └── templates/
        └── index.html          # Panel web
```

## Arquitectura

```
Flask (proceso principal)
  └── Administrador (productor)
        ├── Trabajador 1 ── 3 hilos consumidores
        └── Trabajador 2 ── 3 hilos consumidores
```

- **Flask:** atiende el panel web y crea el administrador cuando se pulsa un botón de inicio.
- **Administrador:** crea los dos trabajadores, genera los 100 trabajos y los pone en la cola.
- **Trabajadores:** cada uno lanza 3 hilos que sacan trabajos de la cola y los procesan.
- **Memoria compartida:** una cola circular de 50 posiciones y los contadores, hechos con `multiprocessing.Array` y `multiprocessing.Value`, más un `Lock` y dos semáforos (`sem_empty` y `sem_full`).
- **Cierre:** al terminar los 100 trabajos, el administrador envía seis valores `-1` (uno por hilo) para que todos los hilos terminen. Después `running` pasa a `false`.

## Requisitos

- Linux (probado en Ubuntu).
- Python 3.8 o superior.
- Las librerías **Flask** y **psutil**.

## Instalación

Desde la carpeta del proyecto:

```bash
python3 -m venv venv_proyecto
source venv_proyecto/bin/activate
pip install flask psutil
```

Si no se quiere usar un entorno virtual, también se puede instalar directo con `pip install flask psutil`.

## Cómo ejecutarlo

```bash
cd Backend
python3 app.py
```

Después abrir en el navegador:

```
http://127.0.0.1:5000
```

Para detener el servidor se usa `Ctrl + C` en la terminal.

## Cómo usar el panel

| Botón | Qué hace |
|---|---|
| **Iniciar (Sincronizado)** | Ejecuta los 100 trabajos con el cerrojo. Al final se debe ver **100 procesados y 0 fallidos** (mensaje verde). |
| **Iniciar (Con Bug de Concurrencia)** | Ejecuta los 100 trabajos sin proteger el contador. Al final se ven **menos de 100 procesados** (mensaje rojo). |
| **Reset** | Termina al administrador y a los trabajadores y deja todo en cero. Sirve también para cancelar una ejecución a la mitad. |

Las tarjetas del panel muestran:

- **Trabajos recibidos:** los que el administrador ha puesto en la cola.
- **En cola (pendientes):** los que todavía esperan a ser tomados por un hilo.
- **Procesados:** el valor del contador compartido `processed`.
- **Fallidos:** en este proyecto no cuenta errores de procesamiento, sino las **actualizaciones que se perdieron por la condición de carrera** (100 menos los procesados).

Una ejecución completa tarda entre 20 y 40 segundos, según el equipo.

## Cómo reproducir la condición de carrera

1. Pulsar **Iniciar (Con Bug de Concurrencia)** y esperar a que termine.
2. Anotar cuántos trabajos quedaron como procesados (siempre es menos de 100 y cambia en cada ejecución).
3. Pulsar **Iniciar (Sincronizado)** y comparar: ahora debe dar 100.
4. Repetir cada modo varias veces y comparar los resultados.

No hace falta pulsar Reset entre ejecuciones; cada inicio crea una memoria compartida nueva.

## Cómo observar procesos e hilos con el sistema operativo

Con el servidor corriendo y una ejecución en curso, abrir **otra terminal** y usar:

```bash
# Árbol de procesos (con PID)
pstree -p $(pgrep -f "python3 app.py" | head -n 1)

# PID, PPID, número de hilos, CPU y memoria
ps -eo pid,ppid,nlwp,%cpu,%mem,rss,cmd | grep -E "app.py|multiprocessing" | grep -v grep

# Hilos de un trabajador (cambiar 5234 por el PID real del trabajador)
ps -L -p 5234

# Monitor en tiempo real (por hilos)
top -H

# Crecimiento de memoria de los trabajadores (cambiar los PID)
watch -n1 'ps -o pid,ppid,rss,%cpu,nlwp -p 5234,5235'

# Información directa desde /proc (cambiar el PID)
grep -E "Threads|VmRSS" /proc/5234/status
```

Notas para leer los resultados:

- Cada trabajador aparece con **4 hilos**: los 3 consumidores y su hilo principal (que solo los crea y espera con `join()`).
- En `pstree` el hilo principal se dibuja como el proceso, y solo los otros 3 salen entre llaves.
- Aparece también un proceso `multiprocessing.resource_tracker`. No es parte de la lógica del proyecto: Python lo crea solo para limpiar semáforos y memoria compartida.
- Después de terminar, el administrador puede verse como proceso zombie (`Z`) hasta que Flask lo recoja en el siguiente inicio o Reset.

## Rutas del servidor

| Ruta | Método | Función |
|---|---|---|
| `/` | GET | Entrega el panel web. |
| `/start` | POST | Inicia una ejecución. Recibe `{"bug": true}` para el modo con bug o `{"bug": false}` para el sincronizado. Responde 400 si ya hay una ejecución activa. |
| `/stats` | GET | Devuelve recibidos, procesados, pendientes, fallidos, si está corriendo y el total. |
| `/reset` | POST | Termina todos los subprocesos y reinicia el estado. |
| `/system` | GET | Devuelve CPU, memoria y la lista de procesos Python con su PID, PPID e hilos. |

## Parámetros que se pueden cambiar

Están al inicio de `Backend/app.py`:

| Parámetro | Valor | Significado |
|---|---|---|
| `TOTAL_JOBS` | 100 | Trabajos por ejecución. |
| `MAX_QUEUE` | 50 | Tamaño de la cola circular. |
| `NUM_WORKERS` | 2 | Procesos trabajadores. |
| `THREADS_PER_WORKER` | 3 | Hilos consumidores por trabajador. |
| `SENTINEL` | -1 | Valor que le dice a un hilo que debe terminar. |

Si se cambia el número de trabajadores o de hilos, el administrador ajusta solo la cantidad de valores `-1` que envía.

## Problemas comunes

- **`Address already in use` (puerto 5000 ocupado):** hay otro servidor o una ejecución anterior abierta. Cerrarla con `Ctrl + C`, o buscar el proceso con `pgrep -f app.py` y terminarlo con `kill`.
- **`ModuleNotFoundError: flask` o `psutil`:** falta instalar las librerías. Activar el entorno virtual y ejecutar `pip install flask psutil`.
- **El panel no cambia después de pulsar Iniciar:** revisar que el servidor siga corriendo en la terminal y recargar la página.
- **Quedaron procesos sueltos después de cerrar el servidor:** buscarlos con `ps -eo pid,ppid,cmd | grep multiprocessing` y terminarlos con `kill`.
- **El porcentaje de CPU no pasa de 100 % por trabajador:** es lo esperado. En Python, el GIL impide que los 3 hilos de un mismo proceso usen varios núcleos a la vez; el paralelismo viene de tener 2 procesos. Con un solo núcleo, el total no pasa de 100 %.
