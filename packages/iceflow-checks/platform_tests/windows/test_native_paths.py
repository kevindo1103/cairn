"""Required Windows acceptance suite. Run via scripts/validate_windows.py.

No skip/fallback: a missing link capability is a BLOCKED validation environment,
not a successful test. These tests operate only in pytest temporary directories.
"""
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from iceflow_harness.cli import main
from iceflow_harness.common import Refused, no_symlinks, outside, read_bytes, write_new
from iceflow_harness.config import default_config
from iceflow_harness.gitview import GitView
from iceflow_harness.probe import export_probe
from iceflow_harness.report import envelope, save_report


@pytest.fixture
def junction(tmp_path):
    if os.name != 'nt':
        pytest.fail('NATIVE_WINDOWS_REQUIRED: this suite must not be counted as Linux PASS')
    target = tmp_path / 'synthetic-target'; target.mkdir()
    alias = tmp_path / 'outside-link'
    command = [os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c',
               'mklink', '/J', str(alias), str(target)]
    result = subprocess.run(command, capture_output=True, check=False, timeout=15)
    assert result.returncode == 0, 'WINDOWS_JUNCTION_SETUP_FAILED'
    assert not alias.is_symlink(), 'Fixture must exercise a junction, not a symlink'
    assert os.lstat(alias).st_file_attributes & 0x400
    assert alias.resolve() == target.resolve()
    try:
        yield alias, target
    finally:
        # Remove only the link. Never recursively delete a junction's target.
        os.rmdir(alias)


@pytest.mark.parametrize('suffix', ['report.json', 'new/report.json', 'new/deeper/report.json'])
def test_windows_junction_containment(junction, suffix):
    alias, target = junction
    with pytest.raises(Refused, match='REPARSE_POINT_REFUSED'):
        outside(alias / suffix, target)
    assert not list(target.iterdir())


def test_windows_direct_write_junction(junction):
    alias, target = junction
    with pytest.raises(Refused, match='REPARSE_POINT_REFUSED'):
        write_new(alias / 'report.json', b'{}')
    assert not list(target.iterdir())


def test_windows_report_junction(junction):
    alias, target = junction
    with pytest.raises(Refused, match='REPARSE_POINT_REFUSED'):
        save_report(envelope('scan', []), alias, target)
    assert not list(target.iterdir())


def test_windows_junction_not_erased_by_parent(junction):
    alias, _ = junction
    with pytest.raises(Refused, match='REPARSE_POINT_REFUSED'):
        no_symlinks(alias / '..' / 'report.json')


def test_windows_junction_cli_init(junction):
    alias, target = junction
    subprocess.run(['git', 'init', str(target)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(target), '-c', 'user.name=Harness test',
                    '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-m', 'Fixture'],
                   check=True, capture_output=True)
    before = set(target.iterdir())
    assert main(['init', '--repo', str(target), '--out', str(alias / 'config.yml')]) == 2
    assert set(target.iterdir()) == before


def test_windows_junction_export(junction):
    alias, target = junction
    # export must refuse before touching its source; the fake source has only a root.
    class View:
        root = target
    with pytest.raises(Refused, match='REPARSE_POINT_REFUSED'):
        export_probe(View(), alias / 'context')
    assert not list(target.iterdir())


def test_windows_junction_read(junction):
    alias, target = junction
    (target / 'synthetic.txt').write_bytes(b'not-sensitive')
    with pytest.raises(Refused, match='REPARSE_POINT_REFUSED'):
        read_bytes(alias / 'synthetic.txt')


def test_windows_dangling_junction(tmp_path):
    target = tmp_path / 'target'; target.mkdir()
    alias = tmp_path / 'link'
    subprocess.run([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', 'mklink', '/J',
                    str(alias), str(target)], check=True, capture_output=True)
    target.rmdir()
    try:
        with pytest.raises(Refused, match='REPARSE_POINT_REFUSED'):
            write_new(alias / 'report.json', b'{}')
        assert not target.exists()
    finally:
        os.rmdir(alias)


def test_windows_real_filesystem_symlink(tmp_path):
    target = tmp_path / 'target.txt'; target.write_bytes(b'original')
    link = tmp_path / 'link.txt'
    try:
        link.symlink_to(target)
    except OSError:
        pytest.fail('WINDOWS_SYMLINK_PRIVILEGE_REQUIRED: native negative test NOT_RUN, not PASS')
    with pytest.raises(Refused, match='SYMLINK_REFUSED'):
        read_bytes(link)
    with pytest.raises(Refused, match='SYMLINK_REFUSED'):
        write_new(link, b'overwritten')
    assert target.read_bytes() == b'original'


def test_windows_junction_chain(junction, tmp_path):
    alias, target = junction
    second = tmp_path / 'second-link'
    subprocess.run([os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', 'mklink', '/J',
                    str(second), str(alias)], check=True, capture_output=True)
    try:
        with pytest.raises(Refused, match='REPARSE_POINT_REFUSED'):
            write_new(second / 'nested' / 'report.json', b'{}')
        assert not list(target.iterdir())
    finally:
        os.rmdir(second)


def test_windows_junction_cli_scan_output(junction, tmp_path, capsys):
    alias, target = junction
    subprocess.run(['git', 'init', str(target)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(target), '-c', 'user.name=Harness test',
                    '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-m', 'Fixture'],
                   check=True, capture_output=True)
    cfg = default_config(target, tmp_path / 'safe-reports')
    cfg['output_dir'] = str(alias / 'reports')
    config = tmp_path / 'config.yml'; config.write_text(yaml.safe_dump(cfg), encoding='utf-8')
    before = set(target.iterdir())
    assert main(['scan', '--config', str(config)]) == 2
    assert 'REPARSE_POINT_REFUSED' in capsys.readouterr().err
    assert set(target.iterdir()) == before


def test_windows_demo_refuses_before_creating_directory(junction):
    from iceflow_harness.demo import run_demo
    alias,target=junction
    before=list(target.iterdir())
    with pytest.raises(Refused,match='REPARSE_POINT_REFUSED'):
        run_demo(alias/'new-demo-output')
    assert list(target.iterdir())==before
