"""Process-safe fair dispatch over the existing frozen, shared key-slot locks."""
import os
import secrets
import threading
from tools import task_library as lib


# The filesystem lock remains authoritative across worker processes.  Inside one
# worker, however, dozens of threads polling that same lock can keep its lock
# file open on Windows and prevent the owner from deleting/replacing it.  Keep
# local contenders out of the filesystem lock while preserving cross-process
# fairness and the per-slot leases below.
_LOCAL_GUARD = threading.Lock()


def paths():
    home=lib.ROOT/'.runtime/dispatch'
    return home/'state.json',home/'control.lock'


def read_state(file):
    value=lib.read(file) if file.exists() else {'schema_version':1,'next_order':0,'owners':{},'waiting':{},'last':{}}
    if not isinstance(value,dict) or value.get('schema_version')!=1:raise ValueError('调度记录无效；保留许可和请求证据，请检查本地记录')
    # Removing a dead wait ticket does not decide the outcome of any reserved POST.
    value['waiting']={k:v for k,v in value['waiting'].items() if lib.alive(v.get('pid'))}
    active={v['owner'] for v in value['waiting'].values()}
    value['owners']={k:v for k,v in value['owners'].items() if k in active}
    return value


def register(state,unit,slots):
    with _LOCAL_GUARD:
        if not slots or any(type(s)!=int or s not in state['slots'] for s in slots):raise ValueError('派发槽位超出冻结许可')
        token=secrets.token_hex(16);owner=lib.digest({k:state[k] for k in ('category','batch','id')})
        file,control=paths()
        with lib.lock(control,wait_seconds=5):
            book=read_state(file)
            if owner not in book['owners']:
                book['next_order']+=1;book['owners'][owner]=book['next_order']
            book['waiting'][token]={'owner':owner,'order':book['owners'][owner],'pid':os.getpid(),'unit':unit,'slots':sorted(set(slots)),'created_at':lib.now()}
            lib.write(file,book)
        return token


def claim(token,slots):
    """Return one lease or None. No credentials, requests or licences are modified."""
    with _LOCAL_GUARD:
        file,control=paths()
        with lib.lock(control,wait_seconds=5):
            book=read_state(file);own=book['waiting'].get(token)
            if not own:return None
            for slot in slots:
                if slot not in own['slots']:raise ValueError('调度槽位不在登记范围内')
                contenders=[(key,v) for key,v in book['waiting'].items() if slot in v['slots']]
                orders=sorted({v['order'] for _,v in contenders});last=book['last'].get(str(slot),0)
                turn=next((n for n in orders if n>last),orders[0])
                winner=next(key for key,v in contenders if v['order']==turn)
                if winner!=token:continue
                lease=lib.lock(lib.ROOT/'.runtime/api-slots'/f'slot-{slot}.lock')
                try:lease.__enter__()
                except ValueError:continue
                book['waiting'].pop(token);book['last'][str(slot)]=own['order']
                try:lib.write(file,book)
                except Exception:lease.__exit__(None,None,None);raise
                return slot,lease
        return None


def unregister(token):
    with _LOCAL_GUARD:
        file,control=paths()
        with lib.lock(control,wait_seconds=5):
            book=read_state(file)
            if token in book['waiting']:book['waiting'].pop(token);lib.write(file,book)
