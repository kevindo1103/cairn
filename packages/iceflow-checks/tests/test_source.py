import pytest
from iceflow_harness.common import Refused, parse_json, safe_rel
from iceflow_harness.config import load_yaml, default_config
from iceflow_harness.gitview import GitView
from iceflow_harness.sourcechecks import model_columns, migration_graph, workflow_check, test_import_check as check_import, diagnostics_check, scan

@pytest.mark.parametrize('value', ['../x', '/etc/passwd', 'a/../b', 'a\\b', 'C:/x', 'a//b', 'a\nfile', './x', ''])
def test_paths_rejected(value):
    with pytest.raises(Refused): safe_rel(value)

def test_json_duplicates():
    with pytest.raises(Refused, match='DUPLICATE'): parse_json('{"a":1,"a":2}')

def test_yaml_on_stays_string():
    assert load_yaml('on: [push]\nflag: true\n')['on'] == ['push']

@pytest.mark.parametrize('raw', ["jobs: {}\njobs: {}", "jobs:\n  a: 1\n  a: 2", "a:\n  steps:\n    x: true\n    x: false"])
def test_yaml_nested_duplicate(raw):
    with pytest.raises(Refused, match='DUPLICATE'): load_yaml(raw)

def test_yaml_alias_fail_explicitly():
    with pytest.raises(Refused, match='ALIAS_UNSUPPORTED'): load_yaml('a: &a 3\nb: *a')

def test_yaml_python_tag_refused():
    with pytest.raises(Refused): load_yaml('!!python/object/apply:os.system ["echo dangerous"]')

def test_minimum_workflow_shape():
    assert workflow_check(b'name: Missing', '.github/workflows/a.yml')[0]['status'] == 'FAIL'

def test_git_reads_committed_not_worktree(repo):
    root, git = repo
    # The oracle is the committed blob, never CRLF-converted working-tree bytes.
    import subprocess
    original = subprocess.check_output(['git', '-C', str(root), 'show', 'HEAD:AGENTS.md'])
    (root / 'AGENTS.md').write_text('uncommitted')
    view = GitView(root)
    assert view.read('AGENTS.md') == original
    assert view.dirty
    assert view.source()['uncommitted_changes_included'] is False

def test_git_batch_blob_hash(repo):
    root, git = repo
    view = GitView(root)
    view.preload(['AGENTS.md', 'CLAUDE.md'])
    assert view.source()['blobs_read']['AGENTS.md'] == git('rev-parse', 'HEAD:AGENTS.md')

def test_source_symlink_refused(repo):
    root, git = repo
    import subprocess
    blob = subprocess.check_output(['git', '-C', str(root), 'hash-object', '-w', '--stdin'],
                                   input=b'never-open-target').decode().strip()
    git('update-index', '--add', '--cacheinfo', '120000,' + blob + ',link.py')
    git('commit', '-m', 'Synthetic Git symlink object, not a local filesystem link')
    with pytest.raises(Refused, match='LINK'): GitView(root).read('link.py')

def test_git_ref_option_injection(repo):
    with pytest.raises(Refused): GitView(repo[0], '--output=/tmp/not-allowed')

def test_model_explicit_sql_name():
    raw = b'class Item(Base):\n __tablename__="items"\n renamed=Column("physical_name",String)\n'
    assert model_columns(raw, ['Item']) == {'items': ['physical_name']}

def test_model_mixins_not_silent_pass():
    with pytest.raises(Refused, match='INHERITANCE'):
        model_columns(b'from sqlalchemy import Column, Integer\nclass I(Mixin,Base):\n __tablename__="i"\n id=Column(Integer)', ['I'])

def test_missing_model():
    with pytest.raises(Refused): model_columns(b'x=1', ['Missing'])

@pytest.mark.parametrize('sources,reason', [
    ({'a.py': b'revision="a"\ndown_revision="b"'}, 'PARENT_MISSING'),
    ({'a.py': b'revision="a"\ndown_revision="b"', 'b.py':b'revision="b"\ndown_revision="a"'}, 'CYCLE'),
    ({'a.py': b'revision="a"\ndown_revision=None', 'b.py':b'revision="b"\ndown_revision=None'}, 'MULTIPLE'),
    ({'a.py': b'revision=get_head()\ndown_revision=None'}, 'UNRESOLVED'),
    ({'a.py': b'revision="a"\ndown_revision=None', 'b.py': b'revision="a"\ndown_revision=None'}, 'DUPLICATE')])
def test_graph_negatives(sources, reason):
    with pytest.raises(Refused, match=reason): migration_graph(sources)

def test_merged_heads():
    assert migration_graph({'a.py':b'revision="a"\ndown_revision=None', 'b.py':b'revision="b"\ndown_revision="a"',
                            'c.py':b'revision="c"\ndown_revision="a"', 'm.py':b'revision="m"\ndown_revision=("b","c")'})['heads'] == ['m']

def test_imported_test_class_warning():
    f = check_import(b'from .test_other import FixtureTests\n', 'backend/tests/test_a.py')
    assert f[0]['code'] == 'POSSIBLE_IMPORTED_TEST_CLASS'
    assert f[0]['details']['collection_executed'] is False

def test_normal_unittest_import_allowed():
    assert check_import(b'from unittest import TestCase\n', 'backend/tests/test_a.py') == []

def test_silent_catch():
    f = diagnostics_check(b'try:\n brew()\nexcept Exception:\n db.rollback()\n', 'backend/router.py')
    assert f[0]['code'] == 'CATCH_ALL_WITHOUT_VISIBLE_DIAGNOSTIC'

def test_visible_logger_is_only_heuristic():
    assert diagnostics_check(b'try:\n brew()\nexcept Exception as e:\n logger.error("failure")\n', 'backend/router.py') == []

def test_scan_does_not_mutate(repo, tmp_path):
    root, git = repo
    before = git('status', '--porcelain')
    view = GitView(root)
    result = scan(view, default_config(root, tmp_path/'reports'))
    assert git('status', '--porcelain') == before
    assert any(f['check'] == 'K04B' and f['status'] == 'NOT_RUN' for f in result)
    assert any(f['check'] == 'F00' and f['status'] == 'WARN' for f in result)
    assert any(f['check'] == 'K07' and f['status'] == 'WARN' for f in result)

def test_sqlalchemy_column_alias():
    source=b'from sqlalchemy import Column as C, Integer\nclass Item(Base):\n __tablename__="items"\n id=C(Integer)\n'
    assert model_columns(source,['Item']) == {'items':['id']}

def test_declared_attr_not_silent_pass():
    source=b'from sqlalchemy import Column, Integer\nclass Item(Base):\n __tablename__="items"\n id=Column(Integer)\n @declared_attr\n def other(cls):\n  return Column(Integer)\n'
    with pytest.raises(Refused,match='DECLARED_ATTR'): model_columns(source,['Item'])

def test_migration_depends_on_not_silent_ignored():
    with pytest.raises(Refused,match='DEPENDENCIES_UNSUPPORTED'):
        migration_graph({'a.py':b'revision="a"\ndown_revision=None\ndepends_on="b"'})
