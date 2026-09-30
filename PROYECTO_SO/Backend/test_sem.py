import multiprocessing as mp
import sys
import time

sem = mp.Semaphore(0)

def child(sem):
    print('Child: waiting on sem', file=sys.stderr)
    sem.acquire()
    print('Child: got sem', file=sys.stderr)

if __name__ == '__main__':
    print('Parent: starting child', file=sys.stderr)
    p = mp.Process(target=child, args=(sem,))
    p.start()
    time.sleep(0.5)
    print('Parent: releasing sem', file=sys.stderr)
    sem.release()
    p.join()
    print('Parent: done', file=sys.stderr)