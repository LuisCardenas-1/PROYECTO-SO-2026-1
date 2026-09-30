"""
Proyecto SO - Monitor de Procesamiento de Imágenes
Demuestra: procesos, hilos, productor-consumidor, race condition, sincronización,
simulación CPU/memoria, estadísticas, deadlock prevention, monitoreo del sistema.
Compatible con Linux y Windows.
"""
from flask import Flask, jsonify, render_template, request
import multiprocessing as mp
import threading
import time
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_TEMPLATES = os.path.join(BASE_DIR, '..', 'Frontend', 'templates')

app = Flask(__name__, template_folder=FRONTEND_TEMPLATES)

# Configuración
MAX_QUEUE = 50
NUM_WORKERS = 2
THREADS_PER_WORKER = 3
TOTAL_JOBS = 100

# Variables compartidas - se inicializan en __main__ con Manager
_manager = None
_queue = None
_head = None
_tail = None
_count = None
_stats_received = None
_stats_processed = None
_stats_pending = None
_stats_failed = None
_is_running = None
_lock = None
_sem_empty = None
_sem_full = None

memory_leak = []

def get_shared():
    """Retorna diccionario con objetos compartidos (inicializa si necesario)."""
    global _manager, _queue, _head, _tail, _count
    global _stats_received, _stats_processed, _stats_pending, _stats_failed, _is_running
    global _lock, _sem_empty, _sem_full
    
    if _manager is None:
        _manager = mp.Manager()
        _queue = _manager.list([0] * MAX_QUEUE)
        _head = _manager.Value('i', 0)
        _tail = _manager.Value('i', 0)
        _count = _manager.Value('i', 0)
        _stats_received = _manager.Value('i', 0)
        _stats_processed = _manager.Value('i', 0)
        _stats_pending = _manager.Value('i', 0)
        _stats_failed = _manager.Value('i', 0)
        _is_running = _manager.Value('b', False)
        _lock = _manager.Lock()
        _sem_empty = _manager.Semaphore(MAX_QUEUE)
        _sem_full = _manager.Semaphore(0)
    
    return {
        'queue': _queue, 'head': _head, 'tail': _tail, 'count': _count,
        'stats_received': _stats_received, 'stats_processed': _stats_processed,
        'stats_pending': _stats_pending, 'stats_failed': _stats_failed,
        'is_running': _is_running, 'lock': _lock,
        'sem_empty': _sem_empty, 'sem_full': _sem_full
    }

def process_image():
    """Simula tarea intensiva en CPU (5M iteraciones) y crecimiento de memoria (1MB/job)."""
    global memory_leak
    dummy = 0
    for i in range(5_000_000):
        dummy += i
    dummy_ram = os.urandom(1024 * 1024)
    memory_leak.append(dummy_ram)

def worker_thread(shr, race_mode):
    """
    Hilo trabajador: consume de la cola (productor-consumidor).
    Usa semáforos para sincronización y lock para exclusión mutua.
    """
    thread_name = threading.current_thread().name
    print(f'[WORKER {thread_name}] Started, race_mode={race_mode}', file=sys.stderr)
    
    queue = shr['queue']
    head = shr['head']
    count = shr['count']
    stats_processed = shr['stats_processed']
    stats_pending = shr['stats_pending']
    stats_failed = shr['stats_failed']
    lock = shr['lock']
    sem_empty = shr['sem_empty']
    sem_full = shr['sem_full']
    
    while True:
        sem_full.acquire()
        lock.acquire()
        
        if stats_processed.value + stats_failed.value >= TOTAL_JOBS:
            lock.release()
            sem_full.release()
            break
            
        job_id = queue[head.value]
        head.value = (head.value + 1) % MAX_QUEUE
        count.value -= 1
        stats_pending.value -= 1
        
        lock.release()
        sem_empty.release()
        
        process_image()
        
        if race_mode:
            temp = stats_processed.value
            time.sleep(0.001)
            stats_processed.value = temp + 1
        else:
            lock.acquire()
            stats_processed.value += 1
            lock.release()
    print(f'[WORKER {thread_name}] Exiting', file=sys.stderr)

def run_worker_process(shr, race_mode):
    """Proceso trabajador: crea múltiples hilos para procesamiento concurrente."""
    threads = []
    for _ in range(THREADS_PER_WORKER):
        t = threading.Thread(target=worker_thread, args=(shr, race_mode))
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

def producer_process(shr, race_mode):
    """Proceso administrador (productor): genera trabajos y lanza trabajadores."""
    print(f'[PRODUCER] Starting, race_mode={race_mode}', file=sys.stderr)
    
    queue = shr['queue']
    head = shr['head']
    tail = shr['tail']
    count = shr['count']
    stats_received = shr['stats_received']
    stats_processed = shr['stats_processed']
    stats_pending = shr['stats_pending']
    stats_failed = shr['stats_failed']
    is_running = shr['is_running']
    lock = shr['lock']
    sem_empty = shr['sem_empty']
    sem_full = shr['sem_full']
    
    head.value = tail.value = count.value = 0
    stats_received.value = stats_processed.value = stats_pending.value = stats_failed.value = 0
    print(f'[PRODUCER] Stats reset', file=sys.stderr)
    
    workers = []
    for _ in range(NUM_WORKERS):
        p = mp.Process(target=run_worker_process, args=(shr, race_mode))
        workers.append(p)
        p.start()
    print(f'[PRODUCER] Started {len(workers)} worker processes', file=sys.stderr)

    for i in range(TOTAL_JOBS):
        sem_empty.acquire()
        lock.acquire()
        queue[tail.value] = i + 1
        tail.value = (tail.value + 1) % MAX_QUEUE
        count.value += 1
        stats_received.value += 1
        stats_pending.value += 1
        lock.release()
        sem_full.release()
        if i % 20 == 0:
            print(f'[PRODUCER] Enqueued job {i+1}, received={stats_received.value}', file=sys.stderr)
        time.sleep(0.05)

    print(f'[PRODUCER] All jobs enqueued, waiting for workers', file=sys.stderr)
    for p in workers:
        p.join()
    
    stats_failed.value = TOTAL_JOBS - stats_processed.value
    is_running.value = False
    print(f'[PRODUCER] Done. processed={stats_processed.value}, failed={stats_failed.value}', file=sys.stderr)

def get_system_stats():
    """Obtiene estadísticas del sistema: CPU, memoria, procesos, hilos."""
    try:
        import psutil
        p = psutil.Process(os.getpid())
        cpu_percent = p.cpu_percent(interval=0.1)
        mem_percent = p.memory_percent()
        
        processes = []
        threads_total = 0
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'num_threads']):
            if 'python' in proc.info['name'].lower():
                processes.append({
                    'pid': proc.info['pid'],
                    'name': proc.info['name'],
                    'cpu': proc.info['cpu_percent'] or 0,
                    'mem': proc.info['memory_percent'] or 0,
                    'threads': proc.info['num_threads'] or 0
                })
                threads_total += proc.info['num_threads'] or 0
        
        return {
            'cpu_percent': cpu_percent,
            'mem_percent': mem_percent,
            'processes': processes,
            'threads_total': threads_total,
            'platform': sys.platform
        }
    except Exception as e:
        return {'error': str(e)}

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/start', methods=['POST'])
def start():
    data = request.json
    race_mode = data.get('bug', False)
    
    shr = get_shared()
    if not shr['is_running'].value:
        shr['is_running'].value = True
        threading.Thread(target=producer_process, args=(shr, race_mode)).start()
        return jsonify({"status": "started", "bug": race_mode})
    return jsonify({"status": "already_running"}), 400

@app.route('/stats')
def stats():
    shr = get_shared()
    return jsonify({
        "received": shr['stats_received'].value,
        "processed": shr['stats_processed'].value,
        "pending": shr['stats_pending'].value,
        "failed": shr['stats_failed'].value,
        "running": bool(shr['is_running'].value),
        "total": TOTAL_JOBS
    })

@app.route('/reset', methods=['POST'])
def reset():
    shr = get_shared()
    global memory_leak
    shr['head'].value = shr['tail'].value = shr['count'].value = 0
    shr['stats_received'].value = shr['stats_processed'].value = shr['stats_pending'].value = shr['stats_failed'].value = 0
    shr['is_running'].value = False
    memory_leak = []
    return jsonify({"status": "reset"})

@app.route('/system')
def system_stats():
    return jsonify(get_system_stats())

if __name__ == '__main__':
    mp.set_start_method('spawn', force=True)
    # Inicializar Manager aquí (dentro de __main__)
    get_shared()
    app.run(host='0.0.0.0', port=5000, debug=False)