"""Verify the complete delivery using the Python 3.11+ standard library only.

Checks integrity and consistency, NOT authorship, policy approval, or ERP safety.
Run BEFORE installing. All manifest paths are relative to the extracted root.
"""
from __future__ import annotations

import argparse
import ast
import base64
import csv
import configparser
import hashlib
import io
import json
import re
import stat
import sys
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path, PurePosixPath


class InvalidDelivery(ValueError):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unique(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise InvalidDelivery('DUPLICATE_JSON_KEY')
        d[k] = v
    return d


def file_at(root, name):
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name or
            name.startswith('/') or any(ord(x) < 32 for x in name) or
            any(p in {'', '.', '..'} for p in name.split('/'))):
        raise InvalidDelivery('UNSAFE_MANIFEST_PATH')
    path = root
    for part in PurePosixPath(name).parts:
        path = path / part
        try:
            info = path.lstat()
        except OSError as exc:
            raise InvalidDelivery('DELIVERY_FILE_MISSING_OR_UNREADABLE:' + name) from exc
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400 or getattr(info, 'st_reparse_tag', 0):
            raise InvalidDelivery('DELIVERY_PATH_ALIAS_REFUSED')
    if not path.is_file() or not path.resolve().is_relative_to(root):
        raise InvalidDelivery('DELIVERY_FILE_KIND_OR_CONTAINMENT')
    return path


def verify(root: Path):
    root = root.resolve(strict=True)
    manifest = file_at(root, 'SHA256SUMS').read_text(encoding='utf-8')
    entries = {}
    for row in manifest.splitlines():
        if '  ' not in row:
            raise InvalidDelivery('MANIFEST_FORMAT')
        expected, name = row.split('  ', 1)
        if not re.fullmatch(r'[0-9a-f]{64}', expected) or name in entries or name == 'SHA256SUMS':
            raise InvalidDelivery('MANIFEST_ENTRY_INVALID')
        actual = file_at(root, name).read_bytes()
        if sha(actual) != expected:
            raise InvalidDelivery('FILE_DIGEST_MISMATCH:' + name)
        entries[name] = expected
    if not entries:
        raise InvalidDelivery('MANIFEST_EMPTY')
    for required in ['RELEASE.json', 'pyproject.toml', 'src/iceflow_harness/__init__.py']:
        if required not in entries:
            raise InvalidDelivery('REQUIRED_MANIFEST_ENTRY_MISSING:' + required)
    release = json.loads(file_at(root, 'RELEASE.json').read_bytes(), object_pairs_hook=unique)
    version = release.get('version')
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise InvalidDelivery('RELEASE_VERSION_INVALID')
    if release.get('package') != 'iceflow-harness':
        raise InvalidDelivery('RELEASE_PACKAGE_INVALID')
    project = tomllib.loads(file_at(root, 'pyproject.toml').read_text(encoding='utf-8'))['project']
    if project['version'] != version or project['name'] != 'iceflow-harness':
        raise InvalidDelivery('SOURCE_METADATA_VERSION_MISMATCH')
    source_init = ast.parse(file_at(root, 'src/iceflow_harness/__init__.py').read_bytes())
    versions = [ast.literal_eval(n.value) for n in source_init.body
                if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '__version__' for t in n.targets)]
    if versions != [version]:
        raise InvalidDelivery('SOURCE_INIT_VERSION_MISMATCH')
    artifacts = release.get('artifacts')
    if not isinstance(artifacts, dict) or set(artifacts) != {'wheel', 'patch', 'bundle', 'validation'}:
        raise InvalidDelivery('ARTIFACT_SET_INCOMPLETE')
    for name, item in artifacts.items():
        if not isinstance(item, dict) or set(item) != {'path', 'sha256'}:
            raise InvalidDelivery('ARTIFACT_RECORD_INVALID')
        if entries.get(item['path']) != item['sha256']:
            raise InvalidDelivery('ARTIFACT_NOT_BOUND:' + name)
        file_at(root, item['path'])
    wheel_path = artifacts['wheel']['path']
    if Path(wheel_path).name != f'iceflow_harness-{version}-py3-none-any.whl':
        raise InvalidDelivery('WHEEL_FILENAME_VERSION_MISMATCH')
    dist = f'iceflow_harness-{version}.dist-info'
    with zipfile.ZipFile(file_at(root, wheel_path)) as z:
        members = z.namelist()
        if len(members) != len(set(members)):
            raise InvalidDelivery('WHEEL_DUPLICATE_MEMBERS')
        meta = Parser().parsestr(z.read(dist + '/METADATA').decode('utf-8'))
        if meta.get('Version') != version or meta.get('Name') != 'iceflow-harness':
            raise InvalidDelivery('WHEEL_METADATA_VERSION_MISMATCH')
        source = {p.relative_to(root / 'src').as_posix(): p for p in (root / 'src/iceflow_harness').rglob('*')
                  if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
        packaged = {m for m in members if m.startswith('iceflow_harness/') and not m.endswith('/')}
        if set(source) != packaged:
            raise InvalidDelivery('SOURCE_WHEEL_FILESET_MISMATCH')
        for member, path in source.items():
            relative = path.relative_to(root).as_posix()
            if relative not in entries or file_at(root, relative).read_bytes() != z.read(member):
                raise InvalidDelivery('SOURCE_WHEEL_BYTES_MISMATCH:' + member)
        # Closed installation surface. Matching RECORD hashes cannot bless extra
        # .pth, modules or .data/scripts outside the reviewed source namespace.
        allowed_metadata = {dist + '/' + n for n in
                            ('METADATA', 'WHEEL', 'RECORD', 'entry_points.txt', 'top_level.txt')}
        license_member = dist + '/licenses/LICENSE'
        if license_member in members:
            if 'LICENSE' not in entries or file_at(root, 'LICENSE').read_bytes() != z.read(license_member):
                raise InvalidDelivery('WHEEL_LICENSE_SOURCE_MISMATCH')
            allowed_metadata.add(license_member)
        if (set(members) - set(source) - allowed_metadata):
            raise InvalidDelivery('WHEEL_UNEXPECTED_INSTALL_MEMBER')
        for info in z.infolist():
            name = info.filename
            if (info.is_dir() or '\\' in name or ':' in name or name.startswith('/')
                    or any(p in {'', '.', '..'} for p in name.split('/'))
                    or stat.S_ISLNK(info.external_attr >> 16)
                    or name.lower().endswith('.pth')):
                raise InvalidDelivery('WHEEL_UNSAFE_INSTALL_MEMBER')
        scripts = project.get('scripts', {})
        if not isinstance(scripts, dict):
            raise InvalidDelivery('SOURCE_ENTRYPOINTS_INVALID')
        ep_name = dist + '/entry_points.txt'
        actual_scripts = {}
        if ep_name in members:
            ep = configparser.ConfigParser(interpolation=None, strict=True)
            ep.optionxform = str
            ep.read_string(z.read(ep_name).decode('utf-8'))
            if set(ep.sections()) != {'console_scripts'} or ep.defaults():
                raise InvalidDelivery('WHEEL_ENTRYPOINTS_UNEXPECTED')
            actual_scripts = dict(ep['console_scripts'])
        if scripts != actual_scripts:
            raise InvalidDelivery('WHEEL_ENTRYPOINTS_MISMATCH')
        if dist + '/top_level.txt' in members and z.read(dist + '/top_level.txt').decode().split() != ['iceflow_harness']:
            raise InvalidDelivery('WHEEL_TOP_LEVEL_MISMATCH')
        wheel_meta = Parser().parsestr(z.read(dist + '/WHEEL').decode('utf-8'))
        if wheel_meta.get_all('Tag') != ['py3-none-any']:
            raise InvalidDelivery('WHEEL_TAG_MISMATCH')
        records = list(csv.reader(io.StringIO(z.read(dist + '/RECORD').decode('utf-8'))))
        if len(records) != len(members) or {row[0] for row in records} != set(members):
            raise InvalidDelivery('WHEEL_RECORD_FILESET_MISMATCH')
        for name, encoded, size in records:
            if name == dist + '/RECORD':
                if encoded or size:
                    raise InvalidDelivery('WHEEL_RECORD_SELF_HASH')
                continue
            data = z.read(name)
            actual = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
            if encoded != 'sha256=' + actual or size != str(len(data)):
                raise InvalidDelivery('WHEEL_RECORD_DIGEST_MISMATCH')
    return {'status': 'PASS', 'scope': 'DELIVERY_INTEGRITY_AND_SOURCE_WHEEL_CONSISTENCY_ONLY',
            'version': version, 'files_verified': len(entries), 'runtime_files_compared': len(source),
            'bundle_git_history': 'VERIFY_WITH_GIT_SEPARATELY', 'authority': 'NONE'}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = p.parse_args()
    try:
        result = verify(args.root)
    except (InvalidDelivery, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        code = str(exc) if isinstance(exc, InvalidDelivery) else 'DELIVERY_PARSE_OR_READ_FAILED'
        print(json.dumps({'status': 'FAIL', 'reason': code, 'authority': 'NONE'}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
