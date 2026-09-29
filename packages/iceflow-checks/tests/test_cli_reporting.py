import json
import logging
from pathlib import Path
import pytest
from iceflow_harness.cli import main
from iceflow_harness.common import Refused, finding
from iceflow_harness.diagnostics import emit_safe_event, safe_event
from iceflow_harness.report import envelope, render_html
from iceflow_harness.probe import docker_command, export_probe
from iceflow_harness.gitview import GitView

def test_install_init_scan(repo,tmp_path,capsys):
    root, git=repo
    config=tmp_path/'harness.yml'
    assert main(['init','--repo',str(root),'--out',str(config)])==0
    assert main(['doctor','--config',str(config)])==0
    assert main(['scan','--config',str(config)])==0
    reports=list((tmp_path/'reports').rglob('report.json'))
    scan=json.loads([r for r in reports if r.parent.name.startswith('scan-')][0].read_text())
    assert scan['outcome']=='PARTIAL' and scan['authority']=='NONE'
    assert git('status','--porcelain')==''

def test_init_inside_target_rejected(repo,capsys):
    root,_=repo
    assert main(['init','--repo',str(root),'--out',str(root/'harness.yml')])==2
    assert not (root/'harness.yml').exists()

def test_init_no_overwrite(repo,tmp_path,capsys):
    p=tmp_path/'harness.yml';p.write_text('original')
    assert main(['init','--repo',str(repo[0]),'--out',str(p)])==2
    assert p.read_text()=='original'

def test_demo_is_runnable(tmp_path,capsys):
    assert main(['demo','--out',str(tmp_path/'demo')])==0
    assert len(list((tmp_path/'demo').rglob('report.html')))==2

def test_fail_is_not_all_pass():
    e=envelope('x',[finding('K02','PASS','TESTS_PASSED'),finding('K04B','NOT_RUN','DB_REQUIRED')])
    assert e['outcome']=='PARTIAL'
    assert e['effective_permissions']==[]

def test_report_escapes_html():
    v=envelope('x',[finding('K02','FAIL','TEST_FAILURE',details={'node':'<script>alert(1)</script>'})])
    h=render_html(v)
    assert '<script>' not in h and '&lt;script&gt;' in h

def test_log_never_exception_content(caplog):
    caplog.set_level(logging.ERROR)
    e=ValueError('Bearer secret-canary /opt/secret.db postgres://admin:password@server')
    assert emit_safe_event(logging.getLogger('harness-test'),reason='COMMAND_FAILED',exception=e,phase='brew',correlation_id='12345678-abcd')
    assert 'secret-canary' not in caplog.text and 'password' not in caplog.text
    assert 'ValueError' in caplog.text and 'COMMAND_FAILED' in caplog.text

def test_logger_failure_does_not_raise():
    class Broken:
        def error(self,*a,**kw): raise OSError('secret')
    assert emit_safe_event(Broken(),reason='COMMAND_FAILED',exception=ValueError(),phase='brew',correlation_id='12345678') is False

@pytest.mark.parametrize('value',['bad\nlog', 'short', '/opt/secret'])
def test_log_correlation_guard(value):
    with pytest.raises(Refused): safe_event('COMMAND_FAILED',ValueError(), 'brew',value)

def test_container_command_has_security_boundary(tmp_path):
    c=docker_command('sha256:'+'a'*64,tmp_path,'iceflow-probe-'+'b'*32)
    for flag in ['--network=none','--read-only','--cap-drop=ALL','--pull=never','--security-opt=no-new-privileges:true','--user=65534:65534']:
        assert flag in c
    assert not any('docker.sock' in p or 'GH_TOKEN' in p for p in c)

def test_container_tag_not_accepted(tmp_path):
    with pytest.raises(Refused,match='DIGEST'): docker_command('python:latest',tmp_path,'iceflow-probe-'+'b'*32)

def test_export_filters_credentials(repo,tmp_path):
    root,git=repo
    (root/'backend/.env.production').write_text('SECRET=synthetic-canary')
    (root/'backend/private.db').write_text('private')
    git('add','.');git('commit','-m','Synthetic forbidden artifacts')
    target=tmp_path/'export'
    export_probe(GitView(root),target)
    assert not (target/'backend/.env.production').exists()
    assert not (target/'backend/private.db').exists()
    assert not (target/'.git').exists()
    assert (target/'probe_worker.py').exists()

def test_mutating_mode_config_refused(repo,tmp_path,capsys):
    import yaml
    from iceflow_harness.config import default_config
    p=tmp_path/'config.yml'
    cfg=default_config(repo[0],tmp_path/'report')
    cfg['mode']='execute'
    p.write_text(yaml.safe_dump(cfg))
    assert main(['doctor','--config',str(p)])==2
    assert 'ONLY_OBSERVE_SUPPORTED' in capsys.readouterr().err

def test_no_merge_deploy_commands():
    from iceflow_harness.cli import parser
    for name in ['merge','deploy','backfill','force-push']:
        with pytest.raises(SystemExit): parser().parse_args([name])
