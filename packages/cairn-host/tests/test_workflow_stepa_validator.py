import tempfile
import unittest
from pathlib import Path
from workflow_stepa_validator import validate

TOKEN = "$" + "{{ github.event_name }}"
BASE = """jobs:
  backend-tests:
    if: needs.branch-name.outputs.backend == 'true' && needs.branch-name.outputs.tier == 'full'
    steps:
      - name: pytest — compare failing set against base
        run: |
          set +e

          if [ "%s" != "pull_request" ]; then
            echo "::notice::Not a pull_request event — nothing to compare against, skipping."
            exit 0
          fi

          echo ok
""" % TOKEN
CANDIDATE = BASE.replace(
    "if: needs.branch-name.outputs.backend == 'true' && needs.branch-name.outputs.tier == 'full'",
    "if: github.event_name == 'pull_request' && needs.branch-name.outputs.backend == 'true' && needs.branch-name.outputs.tier == 'full'",
).replace(
    """          if [ "%s" != "pull_request" ]; then
            echo "::notice::Not a pull_request event — nothing to compare against, skipping."
            exit 0
          fi

""" % TOKEN, "")

class StepAValidatorTests(unittest.TestCase):
    def run_case(self, candidate):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            base, path = root / "base.yml", root / "candidate.yml"
            base.write_text(BASE, encoding="utf-8")
            path.write_text(candidate, encoding="utf-8")
            return validate(base, path)

    def test_approved_condition_delta_matrix_and_shell(self):
        result = self.run_case(CANDIDATE)
        self.assertEqual(result["bash_n"], "PASS")
        self.assertEqual(sum(result["matrix"].values()), 1)

    def test_condition_mutation_rejected(self):
        with self.assertRaises(ValueError):
            self.run_case(CANDIDATE.replace("tier == 'full'", "tier == 'smoke'"))

    def test_shell_mutation_rejected(self):
        with self.assertRaises(ValueError):
            self.run_case(CANDIDATE.replace("echo ok", "echo changed"))
