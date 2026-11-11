"""Tests for publishing: a push GitHub refuses must never end the run. Run: python -m unittest discover -s scripts

Each test builds a throwaway "GitHub" (a bare repo) with two checkouts of it: `run`, standing in for a sync run,
and `other`, standing in for whatever published first (the previous run in its last seconds, or a deploy)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sync  # noqa: E402


def sh(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, text=True, capture_output=True).stdout.strip()


class Publish(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sync-publish-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        hub, self.run, self.other = (os.path.join(self.tmp, n) for n in ("hub.git", "run", "other"))
        sh(self.tmp, "init", "-q", "--bare", "-b", "main", hub)
        # line endings are left alone from the moment of cloning, or Windows would see every file as changed
        sh(self.tmp, "clone", "-q", "-c", "core.autocrlf=false", hub, self.run)
        self.identity(self.run)
        sh(self.run, "checkout", "-q", "-B", "main")
        self.write(self.run, "data.json", "first\n")
        self.write(self.run, "food.json", "dishes\n")
        sh(self.run, "add", ".")
        sh(self.run, "commit", "-q", "-m", "start")
        sh(self.run, "push", "-q", "-u", "origin", "main")
        sh(self.tmp, "clone", "-q", "-c", "core.autocrlf=false", hub, self.other)
        self.identity(self.other)
        self.logged = []
        for p in (mock.patch.object(sync, "ROOT", self.run), mock.patch.object(sync.time, "sleep", lambda s: None),
                  mock.patch.object(sync, "log", self.logged.append)):
            p.start()
            self.addCleanup(p.stop)

    @staticmethod
    def identity(repo):
        sh(repo, "config", "user.name", "test")
        sh(repo, "config", "user.email", "test@example.invalid")
        sh(repo, "config", "core.autocrlf", "false")
        sh(repo, "config", "commit.gpgsign", "false")

    @staticmethod
    def write(repo, name, text):
        with open(os.path.join(repo, name), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)

    @staticmethod
    def read(repo, name):
        with open(os.path.join(repo, name), encoding="utf-8") as f:
            return f.read()

    def other_publishes(self, name, text):
        self.write(self.other, name, text)
        sh(self.other, "commit", "-q", "-am", f"other changed {name}")
        sh(self.other, "push", "-q")

    def on_hub(self, name):
        sh(self.other, "pull", "-q")
        return self.read(self.other, name)

    def test_a_clear_push_is_published(self):
        self.write(self.run, "data.json", "ours\n")
        self.assertTrue(sync.commit("data.json", "Ratings: ours"))
        self.assertEqual(self.on_hub("data.json"), "ours\n")

    def test_a_change_to_another_file_first_is_worked_around(self):
        self.other_publishes("food.json", "more dishes\n")
        self.write(self.run, "data.json", "ours\n")
        self.assertTrue(sync.commit("data.json", "Ratings: ours"))
        self.assertEqual(self.on_hub("data.json"), "ours\n")
        self.assertEqual(self.on_hub("food.json"), "more dishes\n")

    def test_a_clash_on_the_same_file_is_dropped_without_stopping_the_run(self):
        # 11 Nov 2026: the run before published the same rating seconds earlier; this used to raise and end the chain
        self.other_publishes("data.json", "theirs\n")
        self.write(self.run, "data.json", "ours\n")
        self.assertFalse(sync.commit("data.json", "Ratings: ours"))
        self.assertEqual(self.on_hub("data.json"), "theirs\n")           # GitHub keeps what was there
        self.assertEqual(self.read(self.run, "data.json"), "theirs\n")   # and the run now sees the same
        self.assertEqual(sh(self.run, "status", "--porcelain"), "")      # nothing left half done
        self.assertEqual(sh(self.run, "rev-parse", "HEAD"), sh(self.run, "rev-parse", "origin/main"))
        self.assertTrue(any("NOT PUBLISHED" in m for m in self.logged))

    def test_a_file_github_already_has_is_not_an_error(self):
        self.assertTrue(sync.commit("data.json", "Ratings: nothing changed"))
        self.assertEqual(sh(self.run, "rev-parse", "HEAD"), sh(self.run, "rev-parse", "origin/main"))

    def test_the_run_can_publish_again_after_a_clash(self):
        self.other_publishes("data.json", "theirs\n")
        self.write(self.run, "data.json", "ours\n")
        self.assertFalse(sync.commit("data.json", "Ratings: ours"))
        self.write(self.run, "data.json", "ours, on top of theirs\n")
        self.assertTrue(sync.commit("data.json", "Ratings: ours again"))
        self.assertEqual(self.on_hub("data.json"), "ours, on top of theirs\n")


if __name__ == "__main__":
    unittest.main()
