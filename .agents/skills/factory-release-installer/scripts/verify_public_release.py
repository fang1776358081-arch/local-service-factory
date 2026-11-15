"""Verify a saved factory software plan with resumable, credential-free downloads.

This helper never publishes, changes latest, releases locks, or installs software.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

CHUNK = 2 * 1024 * 1024
CDN = 'release-assets.githubusercontent.com,objects.githubusercontent.com'


def digest(file):
    result = hashlib.sha256()
    with file.open('rb') as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(part)
    return result.hexdigest()


def curl(url, *, output=None, byte_range=None, head=False, proxy=None):
    args = ['curl.exe' if sys.platform == 'win32' else 'curl', '--disable',
            '--fail', '--silent', '--show-error', '--proto', '=https',
            '--proto-redir', '=https', '--noproxy', CDN,
            '--connect-timeout', '15', '--max-time', '90']
    if head:
        args += ['--head', '--location', '--output',
                 'NUL' if sys.platform == 'win32' else '/dev/null',
                 '--write-out', '%{url_effective}']
    else:
        args += ['--output', str(output)]
    if byte_range:
        start, end = byte_range
        args += ['--range', f'{start}-{end}', '--max-filesize', str(end-start+2)]
    if proxy:
        args += ['--proxy', proxy]
    # No config file, netrc, token or Authorization. Signed redirect URLs stay in memory.
    result = subprocess.run(args + [url], capture_output=True, timeout=100)
    if result.returncode:
        raise ValueError('Public transport failed; preserved downloads can be resumed')
    return result.stdout.decode('utf-8').strip()


def ranged(url, target, size, expected, protocol, proxy):
    redirected = None
    for _ in range(2):
        try:
            redirected = protocol.public_url(curl(url, head=True, proxy=proxy))
            break
        except (ValueError, subprocess.TimeoutExpired):
            pass
    if not redirected:
        raise ValueError('Public redirect discovery failed')
    parts = target.parent / (target.name + '.parts')
    parts.mkdir(exist_ok=True)
    count = (size + CHUNK - 1) // CHUNK

    def fetch(index):
        start = index * CHUNK
        end = min(size, start + CHUNK) - 1
        part = parts / f'{index:04d}.part'
        if part.is_file() and part.stat().st_size == end-start+1:
            return
        for _ in range(2):
            try:
                curl(redirected, output=part, byte_range=(start, end), proxy=proxy)
                if part.is_file() and part.stat().st_size == end-start+1:
                    return
            except (ValueError, subprocess.TimeoutExpired):
                pass
        raise ValueError(f'Public range {index} failed; resume this same plan')

    with ThreadPoolExecutor(max_workers=6) as pool:
        for done, future in enumerate(as_completed(pool.submit(fetch, i) for i in range(count)), 1):
            future.result()
            if done % 8 == 0 or done == count:
                print(f'Public ranges verified: {done}/{count}', flush=True)
    assembled = target.with_suffix(target.suffix + '.assembling')
    with assembled.open('wb') as stream:
        for index in range(count):
            stream.write((parts / f'{index:04d}.part').read_bytes())
    if assembled.stat().st_size != size or digest(assembled) != expected:
        # Preserve evidence; don't accept correctly sized but corrupt range files.
        raise ValueError('Reassembled installer digest mismatch; inspect saved parts before retrying')
    assembled.replace(target)


def checked_payload(envelope, plan, config, protocol):
    payload = protocol.verify(envelope, config['public_keys'])
    name = f"LocalServiceFactory-{plan['version']}-setup.exe"
    if (payload.get('kind') != 'software' or payload.get('version') != plan['version']
            or payload.get('files') != plan['files']
            or (plan.get('source_sha') and payload.get('source_sha') != plan['source_sha'])
            or payload.get('sha256') != plan['files'][name]):
        raise ValueError('Signed manifest differs from this saved release plan')
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-root', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True,
                        help='Saved release-plan data, not the full command response')
    parser.add_argument('--download-dir', type=Path)
    parser.add_argument('--cached-only', action='store_true',
                        help='Verify existing public-download evidence without network requests')
    args = parser.parse_args()
    root = args.project_root.resolve()
    if not (root / 'factory.py').is_file():
        raise ValueError('Not a factory project')
    sys.path.insert(0, str(root))
    from tools import update_protocol as protocol
    config = json.loads((root / 'distribution/update-config.json').read_text(encoding='utf-8'))
    plan = json.loads(args.plan.read_text(encoding='utf-8'))
    version = plan.get('version', '')
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid plan version')
    installer = f'LocalServiceFactory-{version}-setup.exe'
    names = {installer, installer+'.blockmap', 'latest.yml'}
    if set(plan['files']) != names or any(not re.fullmatch('[0-9a-f]{64}', h) for h in plan['files'].values()):
        raise ValueError('Unexpected release plan files or hashes')
    folder = Path(plan['directory']).resolve()
    sizes = {}
    for name, expected in plan['files'].items():
        source = folder / name
        if not source.is_file() or digest(source) != expected:
            raise ValueError('Local build artifact changed: '+name)
        sizes[name] = source.stat().st_size
    destination = (args.download_dir or root / '.runtime/updates' / ('public-download-'+version)).resolve()
    if destination == folder:
        raise ValueError('Public download evidence must be separate from local build artifacts')
    destination.mkdir(parents=True, exist_ok=True)
    target = plan.get('target', 'unified')
    owner = config['owner']
    repo = config['software_repo']
    configured = config.get('legacy_software_repository')
    if target == 'legacy-software' and isinstance(configured, dict):
        owner, repo = configured.get('owner'), configured.get('repo')
        if not isinstance(owner, str) or not owner or not isinstance(repo, str) or not repo:
            raise ValueError('Invalid legacy software repository identity')
    elif target == 'legacy-software' and owner == 'eish1997' and repo == 'local-service-factory-dev':
        repo = 'local-service-factory-releases'
    elif target != 'unified':
        raise ValueError('Unexpected publication target')
    base = protocol.public_url(f"https://github.com/{owner}/{repo}/releases/download/v{version}/")
    proxy = urllib.request.getproxies().get('https') or urllib.request.getproxies().get('http')
    manifest = destination / 'software-manifest.json'
    if not manifest.is_file():
        if args.cached_only:
            raise ValueError('Cached manifest missing')
        data = protocol.download(base+'software-manifest.json', 1024*1024)
        checked_payload(json.loads(data), plan, config, protocol)
        manifest.write_bytes(data)
    if manifest.stat().st_size > 1024*1024:
        raise ValueError('Manifest too large')
    checked_payload(json.loads(manifest.read_text(encoding='utf-8')), plan, config, protocol)
    for name, expected in plan['files'].items():
        file = destination / name
        size = sizes[name]
        if not (file.is_file() and file.stat().st_size == size and digest(file) == expected):
            if args.cached_only:
                raise ValueError('Cached public file missing or digest mismatch: '+name)
            if name == installer:
                ranged(base+name, file, size, expected, protocol, proxy)
            else:
                data = protocol.download(base+name, size+1)
                if len(data) != size or protocol.sha(data) != expected:
                    raise ValueError('Public file digest mismatch: '+name)
                file.write_bytes(data)
        print('Public SHA256 verified: '+name, flush=True)
    print(json.dumps({'verified': True, 'version': version, 'signature_verified': True,
                      'directory': str(destination), 'cached_only': args.cached_only}), flush=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.TimeoutExpired, KeyError) as error:
        print('Verification failed: '+str(error), file=sys.stderr)
        raise SystemExit(1)
