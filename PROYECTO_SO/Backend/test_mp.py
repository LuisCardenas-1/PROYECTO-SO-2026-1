import multiprocessing as mp
import sys

v = mp.Value('i', 42)

def child(v):
    print('Child read:', v.value, file=sys.stderr)
    v.value = 99
    print('Child wrote:', v.value, file=sys.stderr)

if __name__ == '__main__':
    print('Parent:', v.value, file=sys.stderr)
    p = mp.Process(target=child, args=(v,))
    p.start()
    p.join()
    print('Parent after:', v.value, file=sys.stderr)