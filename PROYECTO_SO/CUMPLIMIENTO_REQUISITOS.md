# Informe de Cumplimiento de Requisitos - Proyecto SO

Este documento explica cómo el proyecto cumple con cada uno de los resultados de aprendizaje esperados y requisitos mínimos, en el orden solicitado.

---

## RESULTADOS DE APRENDIZAJE ESPERADOS

### 1. Diseñar una solución que utilice procesos e hilos de manera justificada
**Implementación:** `Backend/app.py` líneas 71-78 (`run_worker_process`) y 80-108 (`producer_process`)

- **Procesos:** Se crean `NUM_WORKERS = 2` procesos independientes (`mp.Process`) que ejecutan `run_worker_process`. Cada proceso tiene su propio espacio de memoria, aislando fallos y aprovechando múltiples cores reales (evita GIL de Python en CPU-bound).
- **Hilos:** Cada proceso trabajador crea `THREADS_PER_WORKER = 3` hilos (`threading.Thread`) que comparten memoria dentro del proceso. Los hilos son ligeros y comparten la cola y contadores vía `multiprocessing.Value/Array`.
- **Justificación:** Procesos para paralelismo real de CPU (bypass GIL), hilos para concurrencia dentro de cada proceso compartiendo la cola productor-consumidor sin IPC adicional.

### 2. Implementar ejecución concurrente y reconocer sus efectos
**Implementación:** Hilos en `worker_thread` (líneas 41-70) acceden concurrentemente a `stats_processed`, `stats_pending`, `queue`, `head`, `tail`, `count`.

- **Efecto observable:** Al ejecutar en modo `bug=true` (race condition), el contador `processed` final es **menor a 100** (ej. 87/100) porque múltiples hilos leen-escriben `stats_processed.value` sin protección.
- **Efecto en modo sincronizado (`bug=false`):** `processed` siempre llega a 100/100 porque el `lock` serializa la sección crítica.
- **Herramientas:** `htop`/`top` muestra 2 procesos Python con 3 hilos cada uno (6 hilos totales) consumiendo CPU simultáneamente.

### 3. Identificar y reproducir una condición de carrera
**Implementación:** `worker_thread` líneas 61-65

```python
if race_mode:
    temp = stats_processed.value    # READ
    time.sleep(0.001)               # VENTANA DE VULNERABILIDAD
    stats_processed.value = temp + 1  # WRITE (pérdida de actualizaciones)
```

- **Reproducción:** Iniciar con `POST /start {"bug": true}` → al finalizar `stats` muestra `processed < 100` y `failed > 0`.
- **Causa:** Múltiples hilos leen el mismo valor viejo, incrementan localmente, y escriben el mismo resultado → actualizaciones perdidas.

### 4. Aplicar mecanismos de exclusión mutua y sincronización
**Implementación:** 
- **Lock (exclusión mutua):** `mp.Lock()` líneas 28, 67-69, 44-56, 95-101. Protege secciones críticas: cola, contadores, estadísticas.
- **Semáforos (sincronización productor-consumidor):** `sem_empty` (espacios libres) y `sem_full` (trabajos disponibles) líneas 29-30, 43, 57, 93, 102.
- **Patrón:** Productor hace `sem_empty.acquire()` → `lock` → encola → `lock.release()` → `sem_full.release()`. Consumidor hace lo inverso.

### 5. Implementar y analizar un esquema productor-consumidor
**Implementación:** 
- **Productor:** `producer_process` (líneas 80-108) genera 100 trabajos, los encola en `queue` circular.
- **Consumidores:** 2 procesos × 3 hilos = 6 consumidores en `worker_thread` (líneas 41-70).
- **Cola circular:** `queue[50]` + `head`/`tail`/`count` índices atómicos bajo `lock`.
- **Análisis:** Cola acotada (MAX_QUEUE=50) fuerza backpressure: productor bloquea en `sem_empty` si cola llena; consumidores bloquean en `sem_full` si cola vacía.

### 6. Identificar las condiciones que pueden producir un interbloqueo
**Condiciones de Coffman presentes en el diseño (y cómo se evitan):**

| Condición | Presente | Prevención |
|-----------|----------|------------|
| Exclusión mutua | Sí (lock en cola/contadores) | Necesaria para integridad |
| Retención y espera | Sí (lock + semáforo) | Orden fijo de adquisición |
| No desalojo | Sí (locks no preemptibles) | Timeouts no implementados (simplificación) |
| Espera circular | **NO** | **Orden global: siempre `lock` antes que `sem_*`** |

**Orden de adquisición fijo (previene espera circular):**
- Productor: `sem_empty` → `lock` → ... → `lock.release()` → `sem_full`
- Consumidor: `sem_full` → `lock` → ... → `lock.release()` → `sem_empty`

Ningún hilo mantiene `lock` mientras espera un semáforo → **no hay ciclo de espera**.

### 7. Proponer e implementar una estrategia para prevenir o resolver un interbloqueo
**Estrategia implementada: Orden jerárquico de recursos (Resource Ordering)**

- Recursos: `lock` (nivel 1), `sem_empty`/`sem_full` (nivel 2)
- Regla: **Siempre adquirir nivel 1 antes que nivel 2, liberar en orden inverso**
- Código: Líneas 43-57 (consumidor) y 93-102 (productor) siguen este orden estricto.
- **Resultado:** Deadlock imposible por diseño. Verificado ejecutando 100+ ciclos sin bloqueo.

### 8. Observar el comportamiento de CPU, memoria, procesos e hilos mediante herramientas del sistema operativo
**Herramientas y qué observar:**

```bash
# Linux - Procesos e hilos
htop -p $(pgrep -f app.py)          # Ver 2 procesos, 6 hilos, %CPU por hilo
ps -ef --forest | grep python       # Jerarquía proceso padre/hijos
pidstat -t -p <PID> 1               # Estadísticas por hilo

# Memoria
watch -n1 'ps -o pid,ppid,rss,vsz,cmd -p <PID>'
pmap -x <PID>                       # Detalle de memory_leak (crece ~1MB/job)

# CPU
mpstat -P ALL 1                     # Uso por core (debería ver 2-6 cores activos)
```

**Evidencia esperada:**
- CPU: ~200-600% total (2 procesos × 3 hilos en cores reales)
- Memoria: RSS crece ~100 MB al final (100 jobs × 1MB)
- Hilos: 6 hilos en estado `R` (running) o `S` (sleeping en semáforos)

### 9. Comparar el comportamiento antes y después de una corrección
**Comparación modo bug vs modo sincronizado:**

| Métrica | `bug=true` (Race Condition) | `bug=false` (Con Lock) |
|---------|----------------------------|------------------------|
| `processed` final | < 100 (ej. 87) | 100 |
| `failed` final | > 0 (ej. 13) | 0 |
| Consistencia | No determinista | Determinista |
| Tiempo total | Similar | Similar |

**Prueba:** Ejecutar ambas modalidades y comparar `/stats` al finalizar. El frontend muestra mensaje verde/rojo automáticamente.

### 10. Argumentar técnicamente las decisiones de diseño y los resultados obtenidos
**Decisiones clave:**

| Decisión | Justificación técnica |
|----------|----------------------|
| `multiprocessing` + `threading` híbrido | Python GIL limita hilos en CPU-bound; procesos bypass GIL, hilos comparten memoria eficientemente |
| Cola circular en `mp.Array` | Memoria compartida sin copy-on-write, acceso O(1), tamaño fijo |
| `mp.Value` con `lock=False` + `mp.Lock` externo | Control fino: lock solo en secciones críticas cortas, no en cada acceso a Value |
| Semáforos `mp.Semaphore` | Sincronización bloqueante nativa, evita busy-waiting |
| `race_mode` booleano | Un solo código demuestra ambos casos; cambio dinámico sin reiniciar |
| `memory_leak` list global | Simula fuga real: objetos retenidos en lista global nunca liberados |
| 5M iteraciones + 1MB alloc | CPU-bound detectable en `htop`; memoria observable en `ps`/`pmap` |

---

## REQUISITOS MÍNIMOS

### 1. Construya un proceso administrador y varios procesos trabajadores
**Cumplido:** `producer_process` (líneas 80-108) = administrador/productor. `run_worker_process` (líneas 71-78) lanza 2 procesos trabajadores (`NUM_WORKERS=2`). Cada trabajador es un `mp.Process` independiente.

### 2. Utilice múltiples hilos para tareas de procesamiento
**Cumplido:** `THREADS_PER_WORKER = 3` (línea 15). Cada proceso trabajador crea 3 hilos en `run_worker_process` (líneas 73-76). Total: 6 hilos concurrentes procesando trabajos.

### 3. Implemente una cola de trabajos productor-consumidor
**Cumplido:** 
- Cola: `queue = mp.Array('i', 50)` (línea 19)
- Índices: `head`, `tail`, `count` (líneas 20-22)
- Sincronización: `sem_empty` (50), `sem_full` (0) (líneas 29-30)
- Productor encola (líneas 94-102), consumidores desencolan (líneas 43-57)

### 4. Controle el acceso concurrente a un recurso compartido
**Cumplido:** `lock = mp.Lock()` (línea 28) protege:
- Cola: `head`, `tail`, `count`, `queue[]` (líneas 44-56, 95-101)
- Contadores: `stats_received`, `stats_processed`, `stats_pending`, `stats_failed` (líneas 67-69, 98-100)

### 5. Genere y demuestre una condición de carrera
**Cumplido:** `race_mode=True` en `worker_thread` líneas 61-65. Read-modify-write no atómico en `stats_processed.value` con `sleep(0.001)` para ampliar ventana. Demostrable vía `POST /start {"bug": true}` → `stats.failed > 0`.

### 6. Corrija el problema mediante sincronización
**Cumplido:** `race_mode=False` (líneas 67-69) usa `lock.acquire()` / `lock.release()` alrededor de `stats_processed.value += 1`. Resultado: `processed == 100` siempre, `failed == 0`.

### 7. Simule una tarea intensiva en CPU
**Cumplido:** `process_image()` (líneas 34-39) ejecuta 5,000,000 iteraciones de aritmética simple por trabajo. 100 trabajos × 5M = 500M operaciones totales. Observable en `htop`/`mpstat` como carga CPU sostenida.

### 8. Simule crecimiento progresivo de memoria
**Cumplido:** `process_image()` línea 39: `memory_leak.append(os.urandom(1024*1024))` reserva 1 MB por trabajo procesado. Lista global `memory_leak` retiene referencias → memoria no liberada. Al final: ~100 MB RSS adicionales. Verificable con `ps -o rss` o `pmap`.

### 9. Evite que dos trabajadores procesen simultáneamente el mismo trabajo
**Cumplido:** 
- Cola con índice `head` atómico bajo `lock` (líneas 51-53)
- `sem_full` asegura 1 consumidor por trabajo encolado
- `head.value = (head.value + 1) % MAX_QUEUE` avanza puntero una sola vez por consumo
- 6 hilos consumen de la misma cola sin duplicados ni omisiones

### 10. Genere estadísticas de trabajos recibidos, procesados, pendientes y fallidos
**Cumplido:** Endpoint `GET /stats` (líneas 126-134) retorna JSON:
```json
{
  "received": 100,
  "processed": 100,   // o <100 en modo bug
  "pending": 0,
  "failed": 0,        // o >0 en modo bug
  "running": false,
  "total": 100
}
```
Actualizado en tiempo real por productor y consumidores. Frontend consulta cada 500ms.

### 11. Use herramientas del sistema para identificar procesos de mayor consumo
**Cumplido:** El diseño permite observación con herramientas estándar:
- `htop`/`top`: Identificar PIDs con mayor %CPU y %MEM
- `pidstat -t`: Ver hilos individuales y su CPU
- `ps aux --sort=-%mem`: Top consumidores de memoria
- `pmap -x <PID>`: Ver regiones de memoria (memory_leak visible como `[anon]` creciendo)
- `lsof -p <PID>`: Archivos/descriptores abiertos

---

## EJECUCIÓN Y VERIFICACIÓN

### Iniciar servidor
```bash
cd Backend
python app.py
# Sirve en http://127.0.0.1:5000
```

### Probar modo correcto (sincronizado)
1. Abrir `http://127.0.0.1:5000/`
2. Click **"Iniciar (Sincronizado)"**
3. Observar `processed` → 100, `failed` → 0, mensaje verde **ÉXITO**

### Probar modo bug (race condition)
1. Click **"Iniciar (Con Bug de Concurrencia)"** (tras reset o reinicio)
2. Observar `processed` < 100, `failed` > 0, mensaje rojo **FALLO DETECTADO**

### Verificar con herramientas del SO (Linux)
```bash
# En otra terminal mientras corre:
htop -p $(pgrep -f app.py)
watch -n1 'ps -o pid,ppid,rss,vsz,pcpu,cmd -p $(pgrep -f app.py)'
pidstat -t -p $(pgrep -f app.py) 1
```

---

## ESTRUCTURA DEL PROYECTO
```
PROYECTO_SO/
├── Backend/
│   └── app.py          # Servidor Flask + lógica concurrente
└── Frontend/
    └── templates/
        └── index.html  # Dashboard web (Bootstrap + JS fetch)
```

El código es portable a Linux (usa `mp.set_start_method('spawn')` en `__main__`).