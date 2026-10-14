"""Offline, lossless snapshot/restore for DISPOSABLE Phase-4 state only.

Snapshot never modifies source; restore requires a marker and refuses .git
working trees. For future production recovery, work on a restored disposable
clone and use reviewed change-management; NEVER point here at production.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
from datetime import datetime, timezone
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sources.state import (_atomic_bytes, validate_seen, validate_outbox, validate_discovery,
                           StateError)
from scripts.persist_state import merge_seen, merge_outbox, merge_discovery

FILES = ('seen_jobs.json', 'notification_outbox.json', 'discovery_state.json')
VALIDATORS = (validate_seen, validate_outbox, validate_discovery)
BASELINE_COUNT = 93296
BASELINE_HASH = 'b8f71c34e3ecef2ead2bb873ad88fa35435da516f31b90af9e7ebbfa5afaa9c9'


def digest(b):
    return hashlib.sha256(b).hexdigest()


def load_checked(blob, validator):
    return validator(json.loads(blob))


def identity(root):
    return str(root.resolve())


def state_paths(root):
    """Include other pending receipt/state JSON files if physically present."""
    d = root / 'data'
    extra = sorted(x.name for x in d.iterdir() if x.is_file() and
                   ('receipt' in x.name or 'pending' in x.name) and x.name not in FILES)
    # Validated rolling .bak generations are independent recovery evidence.
    backups = sorted(x.name for x in d.glob('*.bak') if x.name[:-4] in FILES or
                     'receipt' in x.name or 'pending' in x.name)
    return list(FILES) + [x for x in extra + backups if x not in FILES]


def snapshot(source, dest, baseline=None):
    source, dest = Path(source).resolve(), Path(dest).resolve()
    if source == dest or source in dest.parents or dest in source.parents:
        raise ValueError('Snapshot must be OUTSIDE the source tree')
    if dest.exists() and any(dest.iterdir()):
        raise FileExistsError('Refusing overwrite of existing snapshot')
    seen_source = (Path(baseline) if baseline else source / 'data/seen_jobs.json')
    baseline_bytes = seen_source.read_bytes()
    if digest(baseline_bytes) != BASELINE_HASH or len(load_checked(baseline_bytes, validate_seen)) != BASELINE_COUNT:
        raise StateError('Immutable 93,296-ID baseline validation failed')
    srcdata = source / 'data'
    manifest = {'schema_version': 1, 'source_kind': 'archived_or_disposable_NOT_LIVE_VERIFIED',
                'source_dir': identity(source), 'captured_at': datetime.now(timezone.utc).isoformat(),
                'baseline_seen_sha256': BASELINE_HASH, 'baseline_seen_count': BASELINE_COUNT,
                'files': {}}
    staged = {}
    validators = dict(zip(FILES, VALIDATORS))
    for name in state_paths(source):
        path = srcdata / name
        if not path.is_file() or path.is_symlink():
            raise StateError(f'Missing or unsafe state file {name}')
        content = path.read_bytes()
        if name in validators:
            obj = load_checked(content, validators[name])
        elif name.endswith(('.json', '.json.bak')):
            obj = json.loads(content)
        else:
            obj = content  # opaque receipt files retained byte-for-byte
        counts = {'ids': len(obj) if name == 'seen_jobs.json' else None,
                  'jobs': len(obj['jobs']) if name == 'notification_outbox.json' else None,
                  'pending_channels': (sum(v.get('status') == 'pending'
                                             for e in obj['jobs'].values() for v in e['channels'].values())
                                       if name == 'notification_outbox.json' else None),
                  'sent_channels': (sum(v.get('status') == 'sent'
                                          for e in obj['jobs'].values() for v in e['channels'].values())
                                    if name == 'notification_outbox.json' else None)}
        manifest['files'][name] = {'sha256': digest(content), 'bytes': len(content),
                                   'mtime_utc': datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat(),
                                   **{k:v for k,v in counts.items() if v is not None}}
        staged[name] = content
    # Save immutable baseline within snapshot independently, not as active state.
    staged['baseline_seen_jobs.json'] = baseline_bytes
    dest.mkdir(parents=True, exist_ok=True)
    for name, content in staged.items():
        _atomic_bytes(dest / name, content)
    _atomic_bytes(dest / 'manifest.json', (json.dumps(manifest, indent=2,sort_keys=True)+'\n').encode())
    return manifest


def restore(snapshot_dir, target):
    snapshot_dir, target = Path(snapshot_dir).resolve(), Path(target).resolve()
    if not (target / '.phase4_disposable').is_file():
        raise ValueError('Missing disposable recovery marker; refusing any writes')
    # Belt-and-braces: refuse any non-temporary restore path, even if someone
    # places a marker in a production checkout or points data/ elsewhere.
    tmp_root = Path(tempfile.gettempdir()).resolve()
    if not target.is_relative_to(tmp_root) or target == tmp_root:
        raise ValueError('Restore target must be a nested disposable temp directory')
    if (target / 'data').is_symlink() or not (target / 'data').resolve().is_relative_to(target):
        raise ValueError('Unsafe state directory (symlink or escape)')
    if (target / '.git').exists():
        raise ValueError('Refusing restore into Git working tree (risk of live checkout)')
    if target == snapshot_dir or target in snapshot_dir.parents or snapshot_dir in target.parents:
        raise ValueError('Snapshot must be independent of target')
    manifest = json.loads((snapshot_dir / 'manifest.json').read_bytes())
    if manifest['baseline_seen_sha256'] != BASELINE_HASH:
        raise StateError('Snapshot baseline identity mismatch')
    baseline = (snapshot_dir / 'baseline_seen_jobs.json').read_bytes()
    if digest(baseline) != BASELINE_HASH or len(load_checked(baseline, validate_seen)) != BASELINE_COUNT:
        raise StateError('Backup baseline corrupted; refusing restore')
    validators = dict(zip(FILES, VALIDATORS))
    plans = {}; quarantine = {}
    # Validate EVERYTHING before creating/modifying any destination file.
    for name, meta in manifest['files'].items():
        if not isinstance(name, str) or Path(name).name != name or name in ('', '.', '..'):
            raise StateError('Unsafe filename in recovery manifest')
        data = (snapshot_dir / name).read_bytes()
        if digest(data) != meta['sha256']:
            raise StateError('Snapshot hash mismatch: ' + name)
        obj = (load_checked(data, validators[name]) if name in validators else
               json.loads(data) if name.endswith(('.json', '.json.bak')) else data)
        targetpath = target / 'data' / name
        if targetpath.is_symlink():
            raise StateError('Symlink target forbidden: ' + name)
        if targetpath.exists():
            before = targetpath.read_bytes()
            try:
                cur = (load_checked(before, validators[name]) if name in validators else
                       json.loads(before) if name.endswith(('.json', '.json.bak')) else before)
            except (ValueError, TypeError, StateError):
                quarantine[name] = before  # preserve corrupt bytes separately, not silently drop
            else:
                if name == 'seen_jobs.json': obj = merge_seen(obj, cur)
                elif name == 'notification_outbox.json': obj = merge_outbox(obj, cur)
                elif name == 'discovery_state.json': obj = merge_discovery(obj, cur)
                elif obj != cur:  # unknown receipt file: refuse instead of erasing newer state
                    raise StateError('Unknown receipt/state conflict needs manual reconciliation: ' + name)
        if name == 'seen_jobs.json':
            obj = merge_seen(obj, load_checked(baseline, validate_seen))
        if name in validators:
            validators[name](obj)
        plans[name] = ((json.dumps(obj, ensure_ascii=False, separators=(',', ':'),sort_keys=True)+'\n').encode()
                       if name in validators or name.endswith(('.json', '.json.bak')) else obj)
    # Never lose corrupt bytes; preserve under a recovery journal in disposable tree.
    journal = target / '.phase4_recovery_journal'
    if journal.exists() and any(journal.iterdir()):
        raise FileExistsError('Existing recovery journal; review before another restore')
    journal.mkdir(exist_ok=True)
    # Journal valid original bytes too; makes replacement errors retryable.
    for name in plans:
        old = target / 'data' / name
        if old.exists():
            _atomic_bytes(journal / name, old.read_bytes())
    for name, content in plans.items():
        _atomic_bytes(target / 'data' / name, content)
    return {'files_restored': list(plans), 'quarantined_corrupt': list(quarantine),
            'seen_ids': len(json.loads(plans['seen_jobs.json'])),
            'outbox_jobs': len(json.loads(plans['notification_outbox.json'])['jobs']),
            'journal': str(journal)}


def main():
    arg = argparse.ArgumentParser()
    sub = arg.add_subparsers(dest='cmd',required=True)
    b = sub.add_parser('snapshot'); b.add_argument('--source', required=True); b.add_argument('--dest',required=True)
    b.add_argument('--baseline',default=None)
    r = sub.add_parser('restore'); r.add_argument('--snapshot',required=True); r.add_argument('--target',required=True)
    args=arg.parse_args()
    val = snapshot(args.source,args.dest,args.baseline) if args.cmd=='snapshot' else restore(args.snapshot,args.target)
    print(json.dumps(val,indent=2))

if __name__=='__main__':
    main()