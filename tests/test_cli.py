import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def setUp(self):
        self.assertTrue((ROOT / 'play.py').exists(), '游戏启动入口尚未实现')

    def run_cli(self, *args, text=None):
        return subprocess.run([sys.executable, str(ROOT / 'play.py'), *args], cwd=ROOT,
                              input=text, capture_output=True, text=True, timeout=20)

    def test_help_documents_defaults(self):
        result = self.run_cli('--help')
        self.assertEqual(result.returncode, 0)
        self.assertIn('--agent', result.stdout)
        self.assertIn('--model', result.stdout)

    def test_full_headless_match_outputs_standings(self):
        result = self.run_cli('--headless', '--agent', 'local', '--rounds', '30', '--seed', '42')
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report['finished'])
        self.assertEqual(len(report['standings']), 8)
        self.assertEqual(report['opponent_source'], 'local')

    def test_plain_quit_and_auto_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            save = str(Path(tmp) / 'save.json')
            result = self.run_cli('--plain', '--agent', 'local', '--save', save, text='buy 1\nauto\nquit\n')
            self.assertEqual(result.returncode, 0, result.stderr)
            state = json.loads(Path(save).read_text())
            self.assertTrue(state['players'][0]['units'])
            resumed = self.run_cli('--plain', '--save', save, text='quit\n')
            self.assertEqual(resumed.returncode, 0)
            self.assertIn('继续', resumed.stdout)
            self.assertEqual(json.loads(Path(save).read_text())['players'], state['players'])

    def test_bad_save_fails_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'save.json'
            path.write_text('broken')
            result = self.run_cli('--plain', '--save', str(path), text='quit\n')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(path.read_text(), 'broken')

    def test_invalid_rounds_rejected(self):
        self.assertNotEqual(self.run_cli('--rounds', '0').returncode, 0)


if __name__ == '__main__':
    unittest.main()
