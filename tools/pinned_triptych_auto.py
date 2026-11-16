"""Bounded API worker for pinned triptych tasks."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from argparse import Namespace
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from tools import pinned_triptych as pinned

ACTIVE = {'starting', 'checking_keys', 'running', 'pausing'}
RETRYABLE = {'transient', 'balance_exhausted', 'authentication_failed', 'retryable_rejection'}


class LocalComposeError(Exception):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def pid_alive(pid):
    try:
        value = int(pid)
        if value <= 0:
            return False
        os.kill(value, 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def _auto(task):
    return task.setdefault('auto_generation', {})


def _write(folder, task):
    pinned.save(Path(folder) / 'task.json', task)


def _pending(task):
    return [group for group in task['groups'] if group.get('status') != 'composed']


def _unresolved(task):
    return any(request.get('status') == 'requesting' and not request.get('provider_source')
               for request in task.get('requests', []))


def start(args):
    folder, task = pinned.read_job(args.job_dir)
    if not args.confirm_paid or args.authorization != 'dashboard_explicit_paid_generation':
        raise ValueError('Automatic generation requires explicit paid-generation confirmation')
    if task.get('status') == 'superseded' or task.get('package_verified'):
        raise ValueError('Task is superseded or already packaged')
    if not _pending(task):
        raise ValueError('All groups are already complete')
    if _unresolved(task):
        raise ValueError('Import or resolve the already claimed group before automatic generation')
    auto = _auto(task)
    if auto.get('status') in ACTIVE and pid_alive(auto.get('worker_pid')):
        print(json.dumps({'started': False, 'already_running': True, 'pid': auto['worker_pid']}))
        return 0
    if len(task.get('requests', [])) >= int(task.get('max_requests', 0)):
        raise ValueError('Task request budget is exhausted')
    auto.update(status='starting', pause_requested=False, authorization=args.authorization,
                requested_max_workers=min(50, max(1, int(args.max_workers))), started_at=now(),
                error=None, worker_pid=None)
    _write(folder, task)
    command = [sys.executable, '-X', 'utf8', str(pinned.ROOT / 'factory.py'), 'pinned-triptych',
               'auto-worker', '--job-dir', str(folder)]
    flags = 0
    if os.name == 'nt':
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    process = subprocess.Popen(command, cwd=str(pinned.DATA_ROOT), env=os.environ.copy(),
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags)
    _, current = pinned.read_job(folder)
    current_auto = _auto(current)
    current_auto['worker_pid'] = process.pid
    _write(folder, current)
    print(json.dumps({'started': True, 'pid': process.pid, 'task_id': task['task_id']}))
    return 0


def pause(args):
    folder, task = pinned.read_job(args.job_dir)
    auto = _auto(task)
    if auto.get('status') not in ACTIVE:
        raise ValueError('Automatic generation is not running')
    auto.update(pause_requested=True, status='pausing', updated_at=now())
    _write(folder, task)
    print(json.dumps({'pausing': True, 'task_id': task['task_id']}))
    return 0


def _base_config():
    import factory
    import image_generate
    image_generate.load_project_env()
    config = image_generate.apply_provider_config(factory.load_json(pinned.ROOT / 'config.json'))
    config.update(model='gpt-image-2.5-flare', quality='medium', api_size='1536x1024', output_format='png')
    return config


def discover_clients(max_workers):
    import image_generate
    from openai import OpenAI
    keys = image_generate.configured_api_keys()
    if not keys:
        raise ValueError('尚未配置 API Key')
    config = _base_config()

    def inspect(pair):
        slot, key = pair
        kwargs = {'api_key': key, 'timeout': 20, 'max_retries': 0}
        if config.get('base_url'):
            kwargs['base_url'] = config['base_url']
        probe = OpenAI(**kwargs)
        for attempt in range(3):
            try:
                ids = {str(getattr(item, 'id', '')) for item in getattr(probe.models.list(), 'data', ())}
                supported = ids & {'gpt-image-2-4k', 'gpt-image-2.5-flare'}
                if supported != {'gpt-image-2.5-flare'}:
                    return None
                generation_kwargs = {key: value for key, value in kwargs.items() if key != 'timeout'}
                return slot, OpenAI(**generation_kwargs)
            except Exception as error:
                if getattr(error, 'status_code', None) in (401, 403) or attempt == 2:
                    return None
                time.sleep(.5 * (2 ** attempt))
        return None

    width = min(20, len(keys))
    with ThreadPoolExecutor(max_workers=width) as pool:
        clients = [item for item in pool.map(inspect, enumerate(keys, 1)) if item]
    if not clients:
        raise ValueError('没有可用的 gpt-image-2.5-flare 密钥')
    return config, clients[:max_workers]


def _reserve(folder, group_index, slot):
    _, task = pinned.read_job(folder)
    group = next(group for group in task['groups'] if int(group['index']) == int(group_index))
    previous = [request for request in task.get('requests', []) if int(request.get('group', 0)) == int(group_index)]
    if group.get('status') == 'composed' or any(request.get('status') == 'requesting' for request in previous):
        return None
    if len(previous) >= 2 or len(task.get('requests', [])) >= int(task.get('max_requests', 0)):
        return None
    request = {'group': int(group_index), 'attempt': len(previous) + 1, 'status': 'requesting',
               'tool': 'api', 'model': 'gpt-image-2.5-flare', 'key_slot': int(slot),
               'reserved_at': now()}
    task.setdefault('requests', []).append(request)
    task['status'] = 'generating'
    auto = _auto(task)
    auto.update(status='running', updated_at=now(), requests_used=len(task['requests']))
    _write(folder, task)
    return str(group['prompt']), request['attempt']


def _safe_error(error):
    from tools.task_request_errors import classify
    kind, rejection = classify(error)
    value = {'error_type': kind or type(error).__name__}
    status = getattr(error, 'status_code', None)
    if type(status) is int and 100 <= status <= 599:
        value['http_status'] = status
    if rejection:
        value['rejection_kind'] = rejection
    try:
        import image_generate
        value.update(image_generate.safe_stage_metadata(error))
    except Exception:
        pass
    return value


def _request(client, config, prompt, generate):
    try:
        return {'ok': True, 'payload': generate(client, config, prompt)}
    except Exception as error:
        return {'ok': False, **_safe_error(error)}


def _record_failure(folder, group_index, slot, failure):
    _, task = pinned.read_job(folder)
    request = next(request for request in reversed(task['requests'])
                   if int(request.get('group', 0)) == int(group_index) and request.get('status') == 'requesting')
    request.update(status='failed', key_slot=int(slot), **failure, finished_at=now())
    auto = _auto(task)
    auto['failed_requests'] = int(auto.get('failed_requests', 0)) + 1
    auto['updated_at'] = now()
    _write(folder, task)


def _record_success(folder, group_index, slot, payload):
    source_dir = Path(folder) / 'auto_sources'
    source_dir.mkdir(exist_ok=True)
    _, task = pinned.read_job(folder)
    request = next(request for request in reversed(task['requests'])
                   if int(request.get('group', 0)) == int(group_index) and request.get('status') == 'requesting')
    attempt = int(request['attempt'])
    source = source_dir / f'group_{int(group_index):02d}_attempt_{attempt}.image'
    temp = source.with_suffix('.tmp')
    temp.write_bytes(payload)
    try:
        with Image.open(temp) as image:
            image.load()
            if image.width < 512 or image.height < 512:
                raise ValueError('Generated panorama is too small')
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    temp.replace(source)
    request.update(provider_sha256=hashlib.sha256(payload).hexdigest(),
                   provider_source=str(source.relative_to(folder)).replace('\\', '/'))
    _write(folder, task)
    try:
        pinned.compose(Namespace(job_dir=str(folder), group=int(group_index), source=str(source)))
    except Exception as error:
        _, failed = pinned.read_job(folder)
        saved_request = next(request for request in reversed(failed['requests'])
                             if int(request.get('group', 0)) == int(group_index)
                             and request.get('provider_source'))
        saved_request.update(status='saved_pending_compose', local_error=type(error).__name__)
        _write(folder, failed)
        raise LocalComposeError() from None
    _, updated = pinned.read_job(folder)
    auto = _auto(updated)
    auto['completed_groups'] = sum(group.get('status') == 'composed' for group in updated['groups'])
    auto['updated_at'] = now()
    _write(folder, updated)


def _recover_saved(folder):
    _, task = pinned.read_job(folder)
    recovered = 0
    for request in task.get('requests', []):
        if request.get('status') not in {'requesting', 'saved_pending_compose'} or not request.get('provider_source'):
            continue
        group = int(request.get('group', 0))
        source = (Path(folder) / str(request['provider_source'])).resolve()
        if not source.is_relative_to(Path(folder).resolve()) or not source.is_file():
            continue
        request['status'] = 'requesting'
        _write(folder, task)
        try:
            pinned.compose(Namespace(job_dir=str(folder), group=group, source=str(source)))
            recovered += 1
        except Exception as error:
            _, task = pinned.read_job(folder)
            saved_request = next(item for item in reversed(task['requests'])
                                 if int(item.get('group', 0)) == group and item.get('provider_source'))
            saved_request.update(status='saved_pending_compose', local_error=type(error).__name__)
            _write(folder, task)
            raise LocalComposeError() from None
        _, task = pinned.read_job(folder)
    return recovered


def run(folder, *, config=None, clients=None, generate=None):
    import image_generate
    folder = Path(folder).resolve()
    _, task = pinned.read_job(folder)
    auto = _auto(task)
    current_pid = auto.get('worker_pid')
    if current_pid and int(current_pid) != os.getpid() and pid_alive(current_pid):
        raise ValueError('Another automatic triptych worker is running')
    auto.update(status='checking_keys', worker_pid=os.getpid(), updated_at=now(), error=None)
    _write(folder, task)
    _recover_saved(folder)
    _, task = pinned.read_job(folder)
    maximum = min(50, max(1, int(auto.get('requested_max_workers', 50))))
    if clients is None:
        config, clients = discover_clients(maximum)
    if config is None:
        config = _base_config()
    generate = generate or image_generate.generate_one
    client_by_slot = dict(clients)
    available = list(client_by_slot)
    quarantined = set()
    queue = [int(group['index']) for group in _pending(task)]
    dispatch_limit = 1
    successes = 0
    fatal = None
    active = {}
    guard = threading.Lock()
    with ThreadPoolExecutor(max_workers=min(maximum, len(available))) as pool:
        while queue or active:
            _, live = pinned.read_job(folder)
            auto = _auto(live)
            if auto.get('pause_requested'):
                auto['status'] = 'pausing'
                _write(folder, live)
            can_schedule = not auto.get('pause_requested') and not fatal
            slots = [slot for slot in available if slot not in quarantined and slot not in active.values()]
            while can_schedule and queue and slots and len(active) < dispatch_limit:
                group = queue.pop(0)
                slot = slots.pop(0)
                reserved = _reserve(folder, group, slot)
                if not reserved:
                    continue
                prompt, _ = reserved
                active[pool.submit(_request, client_by_slot[slot], config, prompt, generate)] = (group, slot)
            if not active:
                break
            completed, _ = wait(active, timeout=.25, return_when=FIRST_COMPLETED)
            for future in completed:
                group, slot = active.pop(future)
                result = future.result()
                if result['ok']:
                    try:
                        with guard:
                            _record_success(folder, group, slot, result['payload'])
                        successes += 1
                        dispatch_limit = min(maximum, len(clients), 5 if successes == 1 else max(5, dispatch_limit * 2))
                    except LocalComposeError:
                        fatal = 'local_compose_failed'
                    except Exception as error:
                        failure = _safe_error(error)
                        with guard:
                            _record_failure(folder, group, slot, failure)
                        fatal = failure['error_type']
                else:
                    failure = {key: value for key, value in result.items() if key not in {'ok', 'payload'}}
                    with guard:
                        _record_failure(folder, group, slot, failure)
                    if failure['error_type'] in {'authentication_failed', 'balance_exhausted'}:
                        quarantined.add(slot)
                    _, latest = pinned.read_job(folder)
                    attempts = sum(int(request.get('group', 0)) == group for request in latest.get('requests', []))
                    if failure['error_type'] in RETRYABLE and attempts < 2:
                        queue.insert(0, group)
                    elif failure.get('rejection_kind') in {'parameters', 'model'}:
                        fatal = failure['error_type']
            _, live = pinned.read_job(folder)
            if len(live.get('requests', [])) >= int(live.get('max_requests', 0)):
                queue.clear()
    _, task = pinned.read_job(folder)
    auto = _auto(task)
    remaining = _pending(task)
    if auto.get('pause_requested'):
        status = 'paused'
    elif not remaining:
        status = 'completed'
        task['status'] = 'awaiting_visual_review'
    else:
        status = 'completed_with_errors'
        task['status'] = 'checkpoint_after_failure'
    auto.update(status=status, worker_pid=None, finished_at=now(), updated_at=now(),
                completed_groups=task['count'] - len(remaining), quarantined_slots=sorted(quarantined),
                error=fatal)
    _write(folder, task)
    return 0 if status in {'completed', 'paused'} else 1


def worker(args):
    try:
        return run(args.job_dir)
    except BaseException as error:
        folder = Path(args.job_dir).resolve()
        try:
            _, task = pinned.read_job(folder)
            auto = _auto(task)
            auto.update(status='failed', worker_pid=None, finished_at=now(), updated_at=now(),
                        error=type(error).__name__)
            task['status'] = 'checkpoint_after_failure'
            _write(folder, task)
        except Exception:
            pass
        raise
