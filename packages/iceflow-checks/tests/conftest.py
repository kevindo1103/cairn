import subprocess
from pathlib import Path
import pytest

@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'target'
    root.mkdir()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args], stderr=subprocess.DEVNULL).decode().strip()
    git('init')
    git('config', 'core.autocrlf', 'false')
    git('config', 'core.safecrlf', 'false')
    git('config', 'user.name', 'Harness test')
    git('config', 'user.email', 'harness-test@example.invalid')
    paths = {
        'AGENTS.md': '# Canonical router\n',
        'CLAUDE.md': '# Legacy instructions\n',
        'backend/models.py': 'from sqlalchemy import Column, Integer, String\nclass InventoryMovement(Base):\n    __tablename__="inventory_movements"\n    id=Column(Integer)\n    inventory_tenant_ref=Column(String)\n',
        'backend/alembic/versions/m1.py': 'revision="m1"\ndown_revision=None\n',
        'backend/requirements.txt': 'alembic\n',
        '.github/workflows/ci.yml': 'name: CI\non: [pull_request]\njobs:\n  a:\n    runs-on: ubuntu-latest\n    steps: [{run: "echo ok"}]\n',
        'backend/tests/test_basic.py': 'def test_ok():\n    assert True\n',
        'backend/modules/chat_ops/router.py': 'try:\n    brew()\nexcept Exception:\n    rollback()\n',
        'frontend/package.json': '{"scripts":{"test:hr":"node --test tests/hr.js"}}'
    }
    for name, text in paths.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode('utf-8'))
    git('add', '.')
    git('commit', '-m', 'Synthetic source fixture')
    return root, git
