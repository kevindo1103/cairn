"""Verify BOTH wheels and all installable members before installation; stdlib only.

This tests integrity/source consistency, not origin, signature or authorization.
The delivery source and this verifier must themselves be obtained from a trusted
reviewed distribution. No hash can establish its own author.
"""
from __future__ import annotations
import argparse
import ast
import base64
import configparser
import csv
import hashlib
import io
import json
import re
import stat
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path

PACKAGES={'iceflow-checks':('iceflow-harness','iceflow_harness'),
          'cairn-engineering':('cairn-engineering','cairn_engineering')}


class InvalidDelivery(ValueError):pass


def require(ok,reason):
    if not ok:raise InvalidDelivery(reason)


def safe(path):
    path=Path(path).absolute()
    for p in reversed((path,*path.parents)):
        try:i=p.lstat()
        except FileNotFoundError:raise InvalidDelivery('DELIVERY_FILE_MISSING') from None
        require(not stat.S_ISLNK(i.st_mode) and not getattr(i,'st_file_attributes',0)&0x400 and
                not getattr(i,'st_reparse_tag',0),'DELIVERY_ALIAS_REFUSED')
    return path


def sha(b):return hashlib.sha256(b).hexdigest()


def inspect_wheel(wheel,root,project):
    distname=project['name'].replace('-','_');version=project['version']
    namespace=distname
    source={p.relative_to(root/'src').as_posix():safe(p).read_bytes() for p in (root/'src'/namespace).rglob('*')
            if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
    require(bool(source),'EMPTY_RUNTIME_SOURCE')
    dist=f'{distname}-{version}.dist-info'
    with zipfile.ZipFile(safe(wheel)) as z:
        names=z.namelist();require(len(names)==len(set(names)) and len(names)<=1024,'WHEEL_MEMBER_LIMIT_OR_DUPLICATE')
        require(sum(x.file_size for x in z.infolist())<=16*1024*1024,'WHEEL_SIZE_LIMIT')
        allowed={dist+'/'+n for n in ('METADATA','WHEEL','RECORD','entry_points.txt','top_level.txt')}
        license_name=dist+'/licenses/LICENSE'
        if license_name in names:
            require(safe(root/'LICENSE').read_bytes()==z.read(license_name),'WHEEL_LICENSE_MISMATCH')
            allowed.add(license_name)
        require(set(names)<=set(source)|allowed,'WHEEL_UNEXPECTED_INSTALL_MEMBER')
        require({n for n in names if n.startswith(namespace+'/')}==set(source),'WHEEL_RUNTIME_SET_MISMATCH')
        for i in z.infolist():
            require(not i.is_dir() and not stat.S_ISLNK(i.external_attr>>16) and
                    '\\' not in i.filename and ':' not in i.filename and not i.filename.startswith('/') and
                    all(p not in {'','.','..'} for p in i.filename.split('/')) and
                    not i.filename.lower().endswith('.pth'),'WHEEL_UNSAFE_MEMBER')
        for n,b in source.items():require(z.read(n)==b,'WHEEL_SOURCE_BYTE_MISMATCH')
        meta=Parser().parsestr(z.read(dist+'/METADATA').decode())
        require(meta.get_all('Name')==[project['name']] and meta.get_all('Version')==[version],'WHEEL_METADATA_MISMATCH')
        # Metadata can cause code installation too (Requires-Dist). A reviewed
        # namespace does not excuse an added dependency or extra.
        normalize=lambda text: re.sub(r'\s+', '', text)
        dependencies=list(project.get('dependencies',[]))
        extras=project.get('optional-dependencies',{})
        expected_dependencies=dependencies+[
            dep+'; extra == "'+extra+'"' for extra,deps in extras.items() for dep in deps]
        require(sorted(map(normalize,meta.get_all('Requires-Dist',[])))==
                sorted(map(normalize,expected_dependencies)),'WHEEL_DEPENDENCY_MISMATCH')
        require(sorted(meta.get_all('Provides-Extra',[]))==sorted(extras),'WHEEL_EXTRAS_MISMATCH')
        require(meta.get('Requires-Python')==project.get('requires-python'),'WHEEL_PYTHON_MISMATCH')
        wheeldoc=Parser().parsestr(z.read(dist+'/WHEEL').decode())
        require(wheeldoc.get_all('Tag')==['py3-none-any'] and wheeldoc.get('Root-Is-Purelib')=='true','WHEEL_TAG_MISMATCH')
        expected=project.get('scripts',{});actual={};entry=dist+'/entry_points.txt'
        if entry in names:
            cp=configparser.ConfigParser(interpolation=None,strict=True);cp.optionxform=str
            cp.read_string(z.read(entry).decode());require(set(cp.sections())=={'console_scripts'} and not cp.defaults(),'ENTRYPOINT_GROUP_INVALID')
            actual=dict(cp['console_scripts'])
        require(expected==actual,'ENTRYPOINT_MISMATCH')
        if dist+'/top_level.txt' in names:require(z.read(dist+'/top_level.txt').decode().split()==[namespace],'WHEEL_TOP_LEVEL_MISMATCH')
        rows=list(csv.reader(io.StringIO(z.read(dist+'/RECORD').decode())))
        require(len(rows)==len(names) and all(len(r)==3 for r in rows) and {r[0] for r in rows}==set(names),'WHEEL_RECORD_SET_INVALID')
        for n,h,size in rows:
            if n==dist+'/RECORD':require(h==size=='','WHEEL_RECORD_SELF_INVALID');continue
            b=z.read(n);encoded=base64.urlsafe_b64encode(hashlib.sha256(b).digest()).rstrip(b'=').decode()
            require(h=='sha256='+encoded and size==str(len(b)),'WHEEL_RECORD_DIGEST_MISMATCH')
    return {'package':project['name'],'version':version,'runtime_files':len(source),'sha256':sha(safe(wheel).read_bytes())}


def verify(root):
    root=safe(root);manifest=safe(root/'SHA256SUMS').read_text();entries={}
    for line in manifest.splitlines():
        require('  ' in line,'MANIFEST_INVALID');h,name=line.split('  ',1)
        require(re.fullmatch('[0-9a-f]{64}',h) and name not in entries and name!='SHA256SUMS','MANIFEST_INVALID')
        require(name and ':' not in name and '\\' not in name and not name.startswith('/') and
                all(p not in {'','.','..'} for p in name.split('/')),'MANIFEST_PATH_INVALID')
        require(sha(safe(root/name).read_bytes())==h,'DELIVERY_DIGEST_MISMATCH');entries[name]=h
    for needed in ('DELIVERY.json','evidence/VALIDATION.json','release/cairn-engineering-additions.patch'):
        require(needed in entries,'REQUIRED_DELIVERY_MEMBER_MISSING')
    results=[]
    for folder,(name,namespace) in PACKAGES.items():
        package=root/'packages'/folder
        require('packages/'+folder+'/pyproject.toml' in entries,'PROJECT_METADATA_NOT_MANIFESTED')
        project=tomllib.loads(safe(package/'pyproject.toml').read_text())['project']
        require(project['name']==name and re.fullmatch(r'\d+\.\d+\.\d+',project['version']),'PACKAGE_VERSION_INVALID')
        wheel=root/'dist'/f'{namespace}-{project["version"]}-py3-none-any.whl'
        require(wheel.relative_to(root).as_posix() in entries,'WHEEL_NOT_MANIFESTED')
        for p in (package/'src'/namespace).rglob('*'):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':require(p.relative_to(root).as_posix() in entries,'RUNTIME_NOT_MANIFESTED')
        results.append(inspect_wheel(wheel,package,project))
    return {'status':'PASS','files_verified':len(entries),'packages':results,'authority':'NONE',
            'scope':'INTEGRITY_AND_INSTALL_SURFACE_ONLY','native_platform_acceptance':'NOT_IMPLIED'}


def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args()
    try:print(json.dumps(verify(a.root),indent=2));return 0
    except Exception as e:
        print(json.dumps({'status':'FAIL','reason':str(e) if isinstance(e,InvalidDelivery) else 'DELIVERY_READ_OR_PARSE_FAILED','authority':'NONE'}));return 1

if __name__=='__main__':raise SystemExit(main())
