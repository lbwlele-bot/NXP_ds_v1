"""Case-scoped inputs for the bounded i.MX943 executor; no hardware actions."""
import hashlib
from pathlib import Path
import re
import yaml


def inside(root, relative):
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise RuntimeError('Task path must be relative to the case')
    root = Path(root).resolve(strict=True)
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise RuntimeError('Task input escapes case or is not a file')
    return path


def mapping(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise RuntimeError(label + ' has missing or unknown fields')
    return value


def read_task(case, profiles, operations):
    case = Path(case).resolve(strict=True)
    path = inside(case, 'records/board-task.yaml')
    raw = path.read_bytes()
    task = mapping(yaml.safe_load(raw),
                   {'schema_version', 'profile', 'authorization', 'artifact'}, 'Task')
    if task['schema_version'] != 1:
        raise RuntimeError('Unsupported task schema')
    profile_id = task['profile']
    if not isinstance(profile_id, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', profile_id):
        raise RuntimeError('Invalid profile id')
    profile_bytes = inside(profiles, profile_id + '.yaml').read_bytes()
    profile = yaml.safe_load(profile_bytes)
    if profile.get('id') != profile_id or profile.get('executor') != 'imx943-a0-lpddr4':
        raise RuntimeError('Unsupported board executor/profile')
    identity = profile.get('controller_identity', {})
    if not re.fullmatch(r'[A-Za-z0-9_-]+', str(identity.get('ftdi_serial', ''))):
        raise RuntimeError('Invalid registered adapter')
    auth = mapping(task['authorization'], {'source', 'operations', 'max_reset_attempts'}, 'Authorization')
    source = inside(case, auth['source'])
    if not source.read_text().strip():
        raise RuntimeError('Authorization source is empty')
    allowed = auth['operations']
    if not isinstance(allowed, list) or not all(isinstance(x, str) for x in allowed):
        raise RuntimeError('Authorization operations must be a list of names')
    if len(set(allowed)) != len(allowed) or set(allowed) - set(operations):
        raise RuntimeError('Unknown or duplicate authorized operation')
    limit = auth['max_reset_attempts']
    if type(limit) is not int or limit < 1:
        raise RuntimeError('Reset attempt budget must be a positive finite integer for this task')
    task = dict(task, case_root=case, profile_data=profile,
                fingerprint=hashlib.sha256(raw + profile_bytes + source.read_bytes()).hexdigest())
    return task


def artifact_binding(task):
    case = task['case_root']
    value = mapping(task['artifact'],
                    {'key', 'id', 'path', 'size', 'sha256', 'build_recipe', 'target_module'}, 'Artifact')
    for key in ('id', 'key', 'build_recipe'):
        if not isinstance(value[key], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', value[key]):
            raise RuntimeError('Invalid artifact ' + key)
    if type(value['size']) is not int or value['size'] <= 0:
        raise RuntimeError('Invalid artifact size')
    if not isinstance(value['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', value['sha256']):
        raise RuntimeError('Invalid artifact SHA-256')
    target = mapping(value['target_module'], {'carrier', 'module', 'ddr', 'software'}, 'Target')
    expected = task['profile_data']['artifact_target']
    if any(target[k] != expected[k] for k in ('carrier', 'module', 'ddr')):
        raise RuntimeError('Artifact target differs from registered module; review target first')
    if not isinstance(target['software'], str) or not target['software'].strip():
        raise RuntimeError('Artifact software identity missing')
    path = inside(case, value['path'])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if path.stat().st_size != value['size'] or digest != value['sha256']:
        raise RuntimeError('Artifact file size/hash differs from task manifest')
    return dict(value, path=path, relative_path=value['path'], case_root=case, case_id=case.name,
                ram_boot_recipe='spl', sd_bootloader_recipe='sd', sd_dev=1,
                usb_identity={'receipt': 'state/usb-identity.receipt.json'})
