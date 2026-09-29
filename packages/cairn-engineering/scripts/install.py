"""Opt-in dedicated-venv installation, not ERP configuration or live activation."""
import argparse
import subprocess
import sys
from pathlib import Path
from verify_install import verify


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',type=Path,required=True,help='Unpacked coherent distribution')
    p.add_argument('--venv',type=Path,required=True,help='NEW dedicated environment; no overwrite')
    a=p.parse_args();checked=verify(a.root)
    v=a.venv.absolute()
    if v.exists():raise SystemExit('Dedicated venv path already exists; not modifying it')
    for part in (v,*v.parents):
        try:i=part.lstat()
        except FileNotFoundError:continue
        import stat
        if stat.S_ISLNK(i.st_mode) or getattr(i,'st_file_attributes',0)&0x400 or getattr(i,'st_reparse_tag',0):
            raise SystemExit('Linked/reparse venv path refused')
    subprocess.run([sys.executable,'-m','venv',str(v)],check=True,timeout=120)
    python=v/('Scripts/python.exe' if sys.platform=='win32' else 'bin/python')
    # The verified project metadata, not a second hardcoded version table,
    # determines the wheel filenames installed by this distribution.
    wheels=[str(a.root/'dist'/
        (item['package'].replace('-', '_')+'-'+item['version']+'-py3-none-any.whl'))
        for item in checked['packages']]
    subprocess.run([str(python),'-m','pip','install',*wheels],check=True,timeout=300)
    subprocess.run([str(python),'-m','pip','check'],check=True,timeout=30)
    print('Installed to dedicated venv only. No Cairn/ERP live configuration changed.')

if __name__=='__main__':main()
