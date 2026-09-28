"""Install-surface negative controls; no mutated wheel is installed or executed."""
import base64
import csv
import hashlib
import importlib.util
import io
from pathlib import Path
import zipfile

import pytest

SCRIPT=Path(__file__).parents[1]/'scripts/verify_install.py'
spec=importlib.util.spec_from_file_location('delivery_install_verifier',SCRIPT)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def fixture(tmp_path,extra=None,entry='tool = synthetic:main\n'):
    root=tmp_path/'pkg';(root/'src/synthetic').mkdir(parents=True)
    source=b'def main(): return 0\n';(root/'src/synthetic/__init__.py').write_bytes(source)
    dist='synthetic-1.0.0.dist-info';record=dist+'/RECORD'
    files={'synthetic/__init__.py':source,
           dist+'/METADATA':b'Metadata-Version: 2.4\nName: synthetic\nVersion: 1.0.0\n',
           dist+'/WHEEL':b'Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n',
           dist+'/entry_points.txt':('[console_scripts]\n'+entry).encode(),
           dist+'/top_level.txt':b'synthetic\n'}
    files.update(extra or {})
    rows=[]
    for n,b in files.items():
        h=base64.urlsafe_b64encode(hashlib.sha256(b).digest()).rstrip(b'=').decode()
        rows.append([n,'sha256='+h,str(len(b))])
    rows.append([record,'','']);out=io.StringIO();csv.writer(out).writerows(rows);files[record]=out.getvalue().encode()
    wheel=tmp_path/'synthetic.whl'
    with zipfile.ZipFile(wheel,'w') as z:
        for name,data in files.items():z.writestr(name,data)
    return wheel,root,{'name':'synthetic','version':'1.0.0','scripts':{'tool':'synthetic:main'}}


def test_valid_minimal_wheel_install_surface(tmp_path):
    assert m.inspect_wheel(*fixture(tmp_path))['runtime_files']==1


@pytest.mark.parametrize('name',['extra.pth','extra.py','synthetic-1.0.0.data/purelib/start.py',
    'synthetic-1.0.0.data/scripts/tool','other-1.0.dist-info/METADATA',
    'synthetic-1.0.0.dist-info/extra.pth','synthetic/extra.py'])
def test_consistently_rehashed_extra_members_refused(tmp_path,name):
    args=fixture(tmp_path,{name:b'# inert synthetic negative fixture\n'})
    with pytest.raises(m.InvalidDelivery):m.inspect_wheel(*args)


def test_consistently_rehashed_wrong_entrypoint_refused(tmp_path):
    with pytest.raises(m.InvalidDelivery,match='ENTRYPOINT_MISMATCH'):
        m.inspect_wheel(*fixture(tmp_path,entry='tool = synthetic:wrong\n'))


def test_missing_required_delivery_files_refused(tmp_path):
    (tmp_path/'SHA256SUMS').write_text('')
    with pytest.raises(m.InvalidDelivery,match='REQUIRED_DELIVERY_MEMBER_MISSING'):m.verify(tmp_path)


@pytest.mark.parametrize('header,reason', [
 ('Requires-Dist: synthetic-unreviewed==1.0\n','WHEEL_DEPENDENCY_MISMATCH'),
 ('Provides-Extra: unreviewed\n','WHEEL_EXTRAS_MISMATCH'),
 ('Requires-Python: >=3.14\n','WHEEL_PYTHON_MISMATCH')])
def test_changed_dependency_metadata_refused(tmp_path,header,reason):
    # Inert metadata fixture; never install the mutated wheel.
    args=fixture(tmp_path,{'synthetic-1.0.0.dist-info/METADATA':
        ('Metadata-Version: 2.4\nName: synthetic\nVersion: 1.0.0\n'+header).encode()})
    with pytest.raises(m.InvalidDelivery,match=reason):m.inspect_wheel(*args)


def test_installer_uses_verified_versions_not_old_filenames(tmp_path, monkeypatch):
    """Observe argv only; do not create a venv or install synthetic wheels."""
    import sys
    import tomllib
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location('pr22_installer', SCRIPT.with_name('install.py'))
    installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
    packages = SCRIPT.parents[2]
    metadata = [tomllib.loads((packages/folder/'pyproject.toml').read_text())['project']
                for folder in ('iceflow-checks', 'cairn-engineering')]
    verified = dict(packages=[dict(package=p['name'], version=p['version']) for p in metadata])
    monkeypatch.setattr(installer, 'verify', lambda root: verified)
    calls = []
    monkeypatch.setattr(installer.subprocess, 'run', lambda argv, **kwargs: calls.append(argv))
    monkeypatch.setattr(sys, 'argv', ['install.py', '--root', str(tmp_path), '--venv', str(tmp_path/'venv')])
    installer.main()
    assert calls[1][1:4] == ['-m', 'pip', 'install']
    assert calls[1][4:] == [str(tmp_path/'dist'/f'{p["name"].replace("-", "_")}-{p["version"]}-py3-none-any.whl')
                            for p in metadata]
    assert not (tmp_path/'venv').exists()
