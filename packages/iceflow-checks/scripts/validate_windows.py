"""Run the mandatory native Windows lane; never turn unavailable links into skips.

Requires the current wheel and pytest already installed in a dedicated venv.
Does not change Developer Mode, privileges, policy or system configuration.
"""
import argparse
import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree

VERSION = "0.1.3"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True, help='New receipt directory outside ERP')
    args = parser.parse_args()
    from iceflow_harness.common import no_symlinks
    args.out = no_symlinks(args.out)
    args.out.mkdir(parents=True, exist_ok=False)
    receipt = {'schema': 'harness-platform-validation-v1', 'version': VERSION,
               'platform': platform.platform(), 'python': platform.python_version(),
               'native_windows': 'NOT_RUN', 'tests': 'NOT_RUN', 'authority': 'NONE'}
    code = 2
    try:
        if os.name != 'nt':
            receipt['reason'] = 'NATIVE_WINDOWS_REQUIRED'
            return code
        if importlib.metadata.version('iceflow-harness') != VERSION:
            receipt['reason'] = 'INSTALLED_WHEEL_VERSION_MISMATCH'
            return code
        import iceflow_harness
        receipt['installed_module'] = str(Path(iceflow_harness.__file__).resolve())
        with tempfile.TemporaryDirectory(prefix='harness-link-capability-') as tmp:
            root = Path(tmp)
            file = root / 'plain.txt'; file.write_bytes(b'synthetic')
            link = root / 'symlink.txt'
            try:
                link.symlink_to(file)
                assert link.is_symlink()
                link.unlink()
                folder = root / 'plain-dir'; folder.mkdir()
                junction = root / 'junction'
                p = subprocess.run([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c',
                                    'mklink', '/J', str(junction), str(folder)],
                                   capture_output=True, timeout=15, check=False)
                try:
                    assert p.returncode == 0 and os.lstat(junction).st_file_attributes & 0x400
                    assert not junction.is_symlink()
                finally:
                    if junction.exists():
                        os.rmdir(junction)
            except (OSError, AssertionError):
                receipt['reason'] = 'WINDOWS_LINK_CAPABILITY_REQUIRED'
                # No fallback mock, pytest.skip, or elevation to manufacture a PASS.
                return code
        receipt['link_capability'] = 'PASS'
        repo = Path(__file__).resolve().parents[1]
        env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1')
        junit = args.out.resolve() / 'unit-and-native-windows.xml'
        receipt['tests'] = 'INCOMPLETE'
        receipt['native_windows'] = 'INCOMPLETE'
        with (args.out / 'pytest.log').open('wb') as log:
            result = subprocess.run([sys.executable, '-m', 'pytest', 'tests', 'platform_tests/windows',
                                     '-q', '--junitxml=' + str(junit)], cwd=repo, env=env,
                                    stdout=log, stderr=subprocess.STDOUT, check=False, timeout=240)
        cases = list(ElementTree.parse(junit).getroot().iter('testcase'))
        failed = sum(c.find('failure') is not None or c.find('error') is not None for c in cases)
        skipped = sum(c.find('skipped') is not None for c in cases)
        native = [c for c in cases if 'test_native_paths' in c.get('classname', '')]
        receipt['tests'] = {'total': len(cases), 'failed': failed, 'skipped': skipped,
                            'native_windows_cases': len(native), 'pytest_exit_code': result.returncode}
        code = 0 if result.returncode == 0 and cases and not failed and not skipped and len(native) == 14 else 1
        receipt['native_windows'] = 'PASS' if code == 0 else 'FAIL'
        return code
    except (OSError, subprocess.SubprocessError, ValueError, ElementTree.ParseError, importlib.metadata.PackageNotFoundError):
        receipt['reason'] = 'VALIDATION_ENVIRONMENT_OR_RESULT_ERROR'
        return 2
    finally:
        (args.out / 'validation.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    raise SystemExit(main())
