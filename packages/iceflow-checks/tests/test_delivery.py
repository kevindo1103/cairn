"""The installer manifest must include real artifacts and match source to wheel bytes."""
import base64
import csv
import hashlib
import importlib.util
import io
import json
import zipfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('delivery_verifier_under_test', Path(__file__).parents[1] / 'scripts/verify_delivery.py')
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def rehash(root):
    entries = [(p.relative_to(root).as_posix(), sha(p.read_bytes())) for p in root.rglob('*')
               if p.is_file() and p.name != 'SHA256SUMS']
    (root / 'SHA256SUMS').write_bytes((''.join(d + '  ' + n + '\n' for n, d in sorted(entries))).encode())


@pytest.fixture
def delivery(tmp_path):
    root = tmp_path / 'delivery'; root.mkdir()
    (root / 'src/iceflow_harness').mkdir(parents=True)
    init = b'__version__ = "0.1.2"\n'
    (root / 'src/iceflow_harness/__init__.py').write_bytes(init)
    (root / 'pyproject.toml').write_bytes(b'[project]\nname="iceflow-harness"\nversion="0.1.2"\n')
    (root / 'dist').mkdir()
    dist = 'iceflow_harness-0.1.2.dist-info'
    members = {'iceflow_harness/__init__.py': init,
               dist + '/METADATA': b'Name: iceflow-harness\nVersion: 0.1.2\n',
               dist + '/WHEEL': b'Wheel-Version: 1.0\nTag: py3-none-any\n'}
    record = io.StringIO(); rows = csv.writer(record)
    for name, data in members.items():
        encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()
        rows.writerow([name, 'sha256=' + encoded, str(len(data))])
    rows.writerow([dist + '/RECORD', '', ''])
    members[dist + '/RECORD'] = record.getvalue().encode()
    wheel = root / 'dist/iceflow_harness-0.1.2-py3-none-any.whl'
    with zipfile.ZipFile(wheel, 'w') as z:
        for name, data in members.items(): z.writestr(name, data)
    artifacts = {'wheel': {'path': wheel.relative_to(root).as_posix(), 'sha256': sha(wheel.read_bytes())}}
    for key in ['patch', 'bundle', 'validation']:
        p = root / (key + '.synthetic'); p.write_bytes(b'synthetic integrity fixture only')
        artifacts[key] = {'path': p.name, 'sha256': sha(p.read_bytes())}
    (root / 'RELEASE.json').write_text(json.dumps({'package': 'iceflow-harness', 'version': '0.1.2', 'artifacts': artifacts}))
    rehash(root)
    return root


def test_delivery_all_artifacts_present_and_consistent(delivery):
    assert verifier.verify(delivery)['status'] == 'PASS'


@pytest.mark.parametrize('key', ['wheel', 'bundle', 'patch', 'validation'])
def test_delivery_missing_artifact_is_failure(delivery, key):
    release = json.loads((delivery / 'RELEASE.json').read_bytes())
    (delivery / release['artifacts'][key]['path']).unlink()
    with pytest.raises(verifier.InvalidDelivery): verifier.verify(delivery)


def test_delivery_same_version_different_runtime_bytes_refused(delivery):
    (delivery / 'src/iceflow_harness/__init__.py').write_bytes(b'__version__="0.1.2"\nEXTRA="wrong source"\n')
    rehash(delivery)  # All independent hashes can match yet source and wheel disagree.
    with pytest.raises(verifier.InvalidDelivery, match='SOURCE_WHEEL_BYTES_MISMATCH'):
        verifier.verify(delivery)


def test_delivery_version_mismatch_refused(delivery):
    p = delivery / 'pyproject.toml'; p.write_bytes(p.read_bytes().replace(b'0.1.2', b'0.1.1'))
    rehash(delivery)
    with pytest.raises(verifier.InvalidDelivery, match='VERSION_MISMATCH'): verifier.verify(delivery)


def test_delivery_checksum_mismatch_refused(delivery):
    (delivery / 'bundle.synthetic').write_bytes(b'corrupt')
    with pytest.raises(verifier.InvalidDelivery, match='DIGEST_MISMATCH'): verifier.verify(delivery)


def test_delivery_omitted_artifact_record_refused(delivery):
    p = delivery / 'RELEASE.json'; release = json.loads(p.read_bytes())
    del release['artifacts']['wheel']; p.write_text(json.dumps(release)); rehash(delivery)
    with pytest.raises(verifier.InvalidDelivery, match='ARTIFACT_SET_INCOMPLETE'): verifier.verify(delivery)


def test_delivery_unsafe_manifest_path_refused(delivery):
    with (delivery / 'SHA256SUMS').open('ab') as p: p.write(b'0'*64 + b'  ../outside\n')
    with pytest.raises(verifier.InvalidDelivery, match='UNSAFE_MANIFEST_PATH'): verifier.verify(delivery)
