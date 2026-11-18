"""Deterministic tests — no network, no model. Runs on stdlib + git binary.

Covers: (a) mirror parser parity vs `git interpret-trailers --parse`,
(b) schema verdicts on fixtures, (c) provgate lint end-to-end on a temp git repo
with planted conformant/violating/exempt/bot/merge commits, (d) residue gate on
planted tracked junk.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
import schema  # noqa: E402

GOOD = """feat(x): widget

Body line here.

Swarm-Card: t_deadbeef
Executed-By: Nimbus (COO, PC node)
Adjudicated-By: d3b0m3n (glass-box directive 2026-11-17)
Receipt-SHA256: """ + "a" * 64 + "\n"

CASES = {
    "good": (GOOD, ["Swarm-Card", "Executed-By", "Adjudicated-By", "Receipt-SHA256"]),
    "no_block": ("feat(x): bare subject only\n", []),
    "middle_not_trailing": ("Swarm-Card: t_deadbeef\n\nsome prose after\n", []),
    "extra_trailer_ok": (GOOD + "Co-Authored-By: Someone <x@y.z>\n", None),
    "continuation": ("docs: y\n\nSwarm-Card: t_deadbeef\nExecuted-By: Nimbus\n (PC node)\n"
                     "Adjudicated-By: pending\nReceipt-SHA256: " + "b" * 64 + "\n", None),
}


def git_parse(msg, cwd):
    p = subprocess.run(["git", "interpret-trailers", "--parse"], input=msg,
                       capture_output=True, text=True, cwd=cwd)
    keys = []
    for ln in p.stdout.rstrip("\n").split("\n"):
        if ": " in ln:
            keys.append(ln.split(": ", 1)[0])
    return keys


class ParserParity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        subprocess.run(["git", "init", "-q", self.tmp], check=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_git_and_mirror_agree(self):
        for name, (msg, _) in CASES.items():
            with self.subTest(name):
                g = git_parse(msg, self.tmp)
                m = [k for k, _ in schema.parse_trailer_block(msg)]
                self.assertEqual(g, m, f"parity broken for {name}")


class SchemaVerdicts(unittest.TestCase):
    CUTOFF = "2026-11-17T00:00:00Z"

    def _ev(self, msg, date="2026-11-17T12:00:00Z", parents="p1", name="Nimbus",
            email="n@x"):
        pairs = schema.parse_trailer_block(msg)
        return schema.evaluate("deadbeef001", msg.split("\n")[0], date, parents,
                               name, email, pairs, self.CUTOFF)

    def test_conformant(self):
        self.assertEqual(self._ev(GOOD)["status"], "conformant")

    def test_missing_key(self):
        msg = GOOD.replace("Receipt-SHA256: " + "a" * 64 + "\n", "")
        v = self._ev(msg)
        self.assertEqual(v["status"], "violations")
        self.assertIn("missing Receipt-SHA256", ";".join(v["reasons"]))

    def test_bad_sha_uppercase_rejected(self):
        v = self._ev(GOOD.replace("a" * 64, "A" * 64))
        self.assertEqual(v["status"], "violations")

    def test_bad_card_id(self):
        v = self._ev(GOOD.replace("t_deadbeef", "t_ZZZZ"))
        self.assertEqual(v["status"], "violations")

    def test_roster_enforced(self):
        v = self._ev(GOOD.replace("Executed-By: Nimbus", "Executed-By: Skynet"))
        self.assertEqual(v["status"], "violations")

    def test_pending_adjudication_visible_debt(self):
        v = self._ev(GOOD.replace(
            "Adjudicated-By: d3b0m3n (glass-box directive 2026-11-17)",
            "Adjudicated-By: pending"))
        self.assertEqual(v["status"], "conformant")

    def test_merge_skip(self):
        v = self._ev(GOOD, parents="p1 p2")
        self.assertEqual(v["status"], "merge_skipped")

    def test_bot_skip(self):
        v = self._ev(GOOD, name="dependabot[bot]")
        self.assertEqual(v["status"], "bot_skipped")

    def test_legacy_skip(self):
        v = self._ev(GOOD, date="2026-11-16T23:59:59Z")
        self.assertEqual(v["status"], "legacy_skipped")

    def test_exempt_needs_reason(self):
        v = self._ev("fix: z\n\nProvenance-Exempt: repo bootstrap\n")
        self.assertEqual(v["status"], "exempt")
        v2 = self._ev("fix: z\n\nProvenance-Exempt:\n")
        self.assertEqual(v2["status"], "violations")

    def test_duplicate_key(self):
        msg = GOOD + "Swarm-Card: t_cafebabe\n"
        v = self._ev(msg)
        self.assertEqual(v["status"], "violations")
        self.assertIn("duplicate", ";".join(v["reasons"]))

    def test_tz_offset_cutoff(self):
        # 05:00+07:00 == 16T22:00Z == BEFORE 17T00Z cutoff -> legacy
        v = self._ev(GOOD, date="2026-11-17T05:00:00+07:00")
        self.assertEqual(v["status"], "legacy_skipped")

    def test_tz_offset_nonzero_minutes(self):
        # 01:00+00:45 (Katmandu-style) == 00:15Z 17th -> AFTER 17T00Z cutoff -> conformant
        v = self._ev(GOOD, date="2026-11-17T01:00:00+00:45")
        self.assertEqual(v["status"], "conformant")
        # 00:30+00:45 == 16T23:45Z -> legacy
        v2 = self._ev(GOOD, date="2026-11-17T00:30:00+00:45")
        self.assertEqual(v2["status"], "legacy_skipped")


class Residue(unittest.TestCase):
    HITS = [".env", "config/.env", "secrets/worldapp.json", "signer.pem", "id_ed25519",
            "node_modules/left-pad/index.js", "src/__pycache__/m.cpython-312.pyc",
            "out/forge-artifacts/X.json", "state.db", "logs/night.log", "a.SECRET"]
    MISSES = ["README.md", ".env.example", ".env.sample", "src/build.sh", "src/main.py",
              "docs/cache-design.md", "out.json", "token_budget_test.py",
              "src/tokens.py", "package-lock.json"]

    def test_hits(self):
        for p in self.HITS:
            with self.subTest(p):
                self.assertIsNotNone(schema.residue_hit(p), f"{p} should be residue")

    def test_misses(self):
        for p in self.MISSES:
            with self.subTest(p):
                self.assertIsNone(schema.residue_hit(p), f"{p} must NOT be residue")


class LintEndToEnd(unittest.TestCase):
    """Full provgate lint on a planted temp repo (uses real git + interpret-trailers)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="provgate-e2e-")
        cls.repo = os.path.join(cls.tmp, "repo")
        os.makedirs(cls.repo)

        def g(*a, stdin=None):
            subprocess.run(["git", *a], cwd=cls.repo, check=True, input=stdin,
                           capture_output=True, text=True)

        g("init", "-q", "-b", "main")
        g("config", "user.name", "Nimbus")
        g("config", "user.email", "nimbus@swarm")
        open(os.path.join(cls.repo, "a.txt"), "w").write("a\n")
        g("add", "a.txt")
        g("commit", "-q", "-m", GOOD, "--date=2026-11-17T12:00:00")           # conformant
        os.remove(os.path.join(cls.repo, "a.txt"))
        open(os.path.join(cls.repo, "b.txt"), "w").write("b\n")
        g("add", "b.txt")
        g("commit", "-q", "-m", "feat: nope\n\nSwarm-Card: t_1\n",
          "--date=2026-11-17T13:00:00")                                        # violation
        open(os.path.join(cls.repo, ".env"), "w").write("x=y\n")
        g("add", ".env")
        g("commit", "-q", "-m", "fix: z\n\nProvenance-Exempt: e2e plant\n",
          "--date=2026-11-17T14:00:00")                                        # exempt + residue

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _lint(self, extra=()):
        p = subprocess.run([sys.executable, os.path.join(ROOT, "provgate.py"), "lint",
                            self.repo, "--json", *extra],
                           capture_output=True, text=True)
        return p

    def test_lint_verdicts(self):
        p = self._lint()
        self.assertIn(p.returncode, (0, 1))
        import json
        rep = json.loads(p.stdout)
        self.assertEqual(rep["counts"]["conformant"], 1)
        self.assertEqual(rep["counts"]["violations"], 1)
        self.assertEqual(rep["counts"]["exempt"], 1)
        self.assertEqual(rep["counts"]["residue"], 1)
        self.assertEqual(rep["violations"][0]["reasons"][0], "bad Swarm-Card: 't_1'")
        self.assertEqual(rep["residue"][0]["path"], ".env")
        self.assertEqual(p.returncode, 1)

    def test_check_message_hook(self):
        mf = os.path.join(self.tmp, "msg")
        open(mf, "w").write(GOOD)
        p = subprocess.run([sys.executable, os.path.join(ROOT, "provgate.py"),
                            "check-message", "-F", mf], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0)
        open(mf, "w").write("feat: bad\n")
        p = subprocess.run([sys.executable, os.path.join(ROOT, "provgate.py"),
                            "check-message", "-F", mf], capture_output=True, text=True)
        self.assertEqual(p.returncode, 1)
        self.assertIn("missing Swarm-Card", p.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
