"""
Proyecto SO - Servidor de procesamiento de imágenes 
Conceptos: procesos, hilos, productor-consumidor, condición de carrera + exclusión mutua, simulación de CPU y memoria,
estadísticas y monitoreo del sistema.
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
SENTINEL = -1        

ctx = mp.get_context('spawn')

SHR = None             
ADMIN = None         
CONTROL = threading.Lock() 

memory_leak = []

def log(msg): print(f'[PID {os.getpid()} | PPID {os.getppid()}] {msg}', file=sys.stderr, flush=True)


# Memoria compartida 
def create_shared():
    """Crea mp.Array / mp.Value directos (memoria compartida entre procesos)."""
    return {
       
        'queue': ctx.Array('i', MAX_QUEUE, lock=False),
        'head': ctx.Value('i', 0, lock=False),
        'tail': ctx.Value('i', 0, lock=False),
        'count': ctx.Value('i', 0, lock=False),
       
        'received': ctx.Value('i', 0, lock=False),
        'processed': ctx.Value('i', 0, lock=False),
        'pending': ctx.Value('i', 0, lock=False),
        'failed': ctx.Value('i', 0, lock=False),
        'is_running': ctx.Value('i', 0, lock=False),
       
        'lock': ctx.Lock(),                      
        'sem_empty': ctx.Semaphore(MAX_QUEUE),   
        'sem_full': ctx.Semaphore(0),            
    }


def get_shared():
    global SHR
    if SHR is None:
        SHR = create_shared()
    return SHR


# rabajo 
def process_image():
    """Tarea intensiva en CPU (5M iteraciones) + crecimiento de memoria (1 MB/job)."""
    dummy = 0
    for i in range(5_000_000):
        dummy += i
    memory_leak.append(os.urandom(1024 * 1024))


def enqueue(shr, value):
    """Productor: protocolo sem_empty -> lock -> escribir -> lock -> sem_full."""
    shr['sem_empty'].acquire()
    shr['lock'].acquire()
    shr['queue'][shr['tail'].value] = value
    shr['tail'].value = (shr['tail'].value + 1) % MAX_QUEUE
    shr['count'].value += 1
    if value != SENTINEL:
        shr['received'].value += 1
        shr['pending'].value += 1
    shr['lock'].release()
    shr['sem_full'].release()


def worker_thread(shr, race_mode):
    """Hilo consumidor. Termina al recibir el centinela (-1)."""
    name = threading.current_thread().name
    log(f'Hilo {name} iniciado (race_mode={race_mode})')

    while True:
        shr['sem_full'].acquire()
        shr['lock'].acquire()
        job = shr['queue'][shr['head'].value]
        shr['head'].value = (shr['head'].value + 1) % MAX_QUEUE
        shr['count'].value -= 1
        if job != SENTINEL:
            shr['pending'].value -= 1
        shr['lock'].release()
        shr['sem_empty'].release()

        if job == SENTINEL:
            break

        process_image()

        if race_mode:
            temp = shr['processed'].value
            time.sleep(0.001)
            shr['processed'].value = temp + 1
        else:
            shr['lock'].acquire()
            shr['processed'].value += 1
            shr['lock'].release()

    log(f'Hilo {name} finalizado')


def run_worker_process(shr, race_mode):
    """Proceso trabajador: lanza sus hilos y espera a que terminen."""
    log(f'Trabajador iniciado con {THREADS_PER_WORKER} hilos')
    threads = [threading.Thread(target=worker_thread, args=(shr, race_mode))
               for _ in range(THREADS_PER_WORKER)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    log('Trabajador finalizado')


def admin_process(shr, race_mode):
    """Proceso administrador (productor): lanza trabajadores y encola trabajos."""
    log(f'Administrador iniciado (race_mode={race_mode})')

    workers = [ctx.Process(target=run_worker_process, args=(shr, race_mode))
               for _ in range(NUM_WORKERS)]
    for p in workers:
        p.start()
    log(f'Trabajadores creados: {[p.pid for p in workers]}')

    for i in range(TOTAL_JOBS):
        enqueue(shr, i + 1)
        time.sleep(0.05)    

    for _ in range(NUM_WORKERS * THREADS_PER_WORKER):
        enqueue(shr, SENTINEL)
    log('Trabajos y centinelas encolados; esperando trabajadores')

    for p in workers:
        p.join()

    # Trabajos que se terminaron pero no quedaron contados (carrera)
    shr['failed'].value = TOTAL_JOBS - shr['processed'].value
    shr['is_running'].value = 0
    log(f"Finalizado. processed={shr['processed'].value}, failed={shr['failed'].value}")


# Reset 
def kill_tree(proc):
    """Mata al administrador y a todos sus descendientes (trabajadores)."""
    import psutil
    try:
        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)
        parent.kill()
        for c in children:
            try:
                c.kill()
            except psutil.NoSuchProcess:
                pass
    except psutil.NoSuchProcess:
        pass
    proc.join(timeout=5)


# Monitoreo del SO 
def get_system_stats():
    """CPU, memoria, procesos e hilos de los procesos Python."""
    try:
        import psutil
        cpu_percent = psutil.cpu_percent(interval=0.1)

        processes = []
        threads_total = 0
        mem_total = 0.0
        for proc in psutil.process_iter(['pid', 'ppid', 'name', 'cpu_percent', 'memory_percent', 'num_threads']):
            if 'python' in (proc.info['name'] or '').lower():
                mem = proc.info['memory_percent'] or 0
                processes.append({
                    'pid': proc.info['pid'],
                    'ppid': proc.info['ppid'],
                    'name': proc.info['name'],
                    'cpu': proc.info['cpu_percent'] or 0,
                    'mem': mem,
                    'threads': proc.info['num_threads'] or 0
                })
                threads_total += proc.info['num_threads'] or 0
                mem_total += mem

        return {
            'cpu_percent': cpu_percent,
            'mem_percent': mem_total,
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
    global SHR, ADMIN
    data = request.get_json(silent=True) or {}
    race_mode = bool(data.get('bug', False))

    with CONTROL:
        if ADMIN is not None and ADMIN.is_alive():
            return jsonify({"status": "already_running"}), 400

        SHR = create_shared()              
        SHR['is_running'].value = 1
        ADMIN = ctx.Process(target=admin_process, args=(SHR, race_mode))
        ADMIN.start()
        log(f'Flask lanzó el administrador PID {ADMIN.pid}')
        return jsonify({"status": "started", "bug": race_mode})


@app.route('/stats')
def stats():
    shr = get_shared()
    return jsonify({
        "received": shr['received'].value,
        "processed": shr['processed'].value,
        "pending": shr['pending'].value,
        "failed": shr['failed'].value,
        "running": bool(shr['is_running'].value),
        "total": TOTAL_JOBS
    })


@app.route('/reset', methods=['POST'])
def reset():
    global SHR, ADMIN
    with CONTROL:
        if ADMIN is not None:
            if ADMIN.is_alive():
                kill_tree(ADMIN)           
                log('Reset: administrador y trabajadores terminados')
            ADMIN = None
        SHR = create_shared()           
    return jsonify({"status": "reset"})


@app.route('/system')
def system_stats():
    return jsonify(get_system_stats())


if __name__ == '__main__':
    get_shared()
    log('Flask (proceso principal) iniciado')
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
