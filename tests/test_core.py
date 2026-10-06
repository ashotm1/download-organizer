import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from organizer import folders as fl
from organizer import motw
from organizer.actions import Mover
from organizer.classifier import ASK, AUTO, NO_MATCH, NONE, LlmResult, decide
from organizer.history import History
from organizer.watcher import DownloadWatcher, wait_until_complete


def llm(folder, confidence="high"):
    return LlmResult(folder, confidence, "because", "")


class DecideTests(unittest.TestCase):
    def test_rule_and_model_agree_moves(self):
        self.assertEqual(decide("cs201", None, llm("cs201"), False)[:2], (AUTO, "cs201"))

    def test_rule_and_source_agree_without_model(self):
        self.assertEqual(decide("cs201", "cs201", None, False)[:2], (AUTO, "cs201"))

    def test_rule_alone_without_model_asks(self):
        self.assertEqual(decide("cs201", None, None, False)[:2], (ASK, "cs201"))

    def test_model_disagrees_with_rule_asks_with_rule(self):
        self.assertEqual(decide("cs201", None, llm("cs301"), False)[:2], (ASK, "cs201"))

    def test_rule_and_source_conflict_asks(self):
        self.assertEqual(decide("cs201", "cs301", llm("cs301"), False)[:2], (ASK, "cs301"))

    def test_model_alone_asks_unless_enabled(self):
        self.assertEqual(decide(None, None, llm("ger101"), False)[:2], (ASK, "ger101"))
        self.assertEqual(decide(None, None, llm("ger101"), True)[:2], (AUTO, "ger101"))
        self.assertEqual(decide(None, None, llm("ger101", "medium"), True)[:2], (ASK, "ger101"))

    def test_nothing_is_no_match(self):
        self.assertEqual(decide(None, None, llm(NONE), True)[0], NO_MATCH)
        self.assertEqual(decide(None, None, None, True)[0], NO_MATCH)


class FolderRuleTests(unittest.TestCase):
    def setUp(self):
        self.folders = [fl.Folder(k, Path(k), patterns=fl.code_patterns(k, a))
                        for k, a in [("cs201", []), ("cs301", []), ("ger101", ["German 101"])]]

    def test_code_variants_match(self):
        for text in ["CS 201", "CS201", "cs-201", "HW4_cs201", "CompSci 201", "COMP SCI 201"]:
            self.assertIn("cs201", fl.score(self.folders, "", "", text), text)

    def test_no_partial_numbers(self):
        self.assertEqual(fl.score(self.folders, "", "", "CS 2011 and ACS201"), {})

    def test_alias(self):
        self.assertIn("ger101", fl.score(self.folders, "", "", "Welcome to German 101!"))

    def test_winner_needs_clear_margin(self):
        self.assertEqual(fl.rule_winner({"cs301": 4, "cs201": 1}), "cs301")
        self.assertIsNone(fl.rule_winner({"cs301": 2, "cs201": 1.5}))

    def test_unknown_course_code(self):
        self.assertEqual(fl.unknown_course_code(self.folders, "cs285_hw1.pdf", "CS 201 prerequisite"), "cs285")
        self.assertIsNone(fl.unknown_course_code(self.folders, "hw1.pdf", "ISBN 978 page 123 CS 201"))

    def test_sanitize(self):
        self.assertEqual(fl.sanitize_folder_name(' bad:/name. '), "badname")


class MotwTests(unittest.TestCase):
    RAW = ("[ZoneTransfer]\r\nZoneId=3\r\n"
           "ReferrerUrl=https://canvas.example.edu/courses/12345/files/1?module_item_id=2\r\n"
           "HostUrl=https://cdn.example.net/x.pdf?token=secret\x00\r\n")

    def test_parse_and_source_key(self):
        m = motw.parse(self.RAW)
        self.assertTrue(m.from_internet)
        self.assertEqual(m.host_url, "https://cdn.example.net/x.pdf?token=secret")
        self.assertEqual(motw.source_key(m), "canvas.example.edu/courses/12345")
        self.assertEqual(motw.clean_url(m.host_url), "https://cdn.example.net/x.pdf")

    def test_generic_host_is_not_a_source(self):
        self.assertIsNone(motw.source_key(motw.parse("ZoneId=3\nHostUrl=https://smallpdf.com/")))


class FileSystemTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_watcher_only_reports_browser_downloads(self):
        seen, event = [], threading.Event()
        watcher = DownloadWatcher(self.dir, [".pdf"], "strict", lambda p, t: (seen.append((p.name, t)), event.set()))
        watcher.start()
        try:
            (self.dir / "copied.pdf").write_bytes(b"%PDF copy")      # user copies a file in
            tmp = self.dir / "real.pdf.crdownload"
            tmp.write_bytes(b"%PDF data")
            tmp.rename(self.dir / "real.pdf")                        # browser completes a download
            self.assertTrue(event.wait(5))
            time.sleep(0.5)
        finally:
            watcher.stop()
        self.assertEqual(seen, [("real.pdf", True)])

    def test_wait_until_complete(self):
        f = self.dir / "a.pdf"
        f.write_bytes(b"x" * 10)
        self.assertTrue(wait_until_complete(f, timeout_s=5, poll_s=0.1))
        self.assertFalse(wait_until_complete(self.dir / "missing.pdf", timeout_s=1, poll_s=0.1))

    def test_move_collision_and_undo(self):
        downloads, dest = self.dir / "dl", self.dir / "cs201"
        downloads.mkdir(), dest.mkdir()
        (dest / "hw.pdf").write_text("old")
        src = downloads / "hw.pdf"
        src.write_text("new")
        mover = Mover(self.dir)
        move_id, moved = mover.move(src, dest)
        self.assertEqual(moved.name, "hw (1).pdf")
        self.assertEqual((dest / "hw.pdf").read_text(), "old")
        self.assertEqual(mover.last_undoable(), move_id)
        back = mover.undo(move_id)
        self.assertEqual(back, src)
        self.assertEqual(src.read_text(), "new")
        self.assertIsNone(mover.last_undoable())

    def test_history_learns_consistent_sources_only(self):
        h = History(self.dir)
        kw = dict(how="confirmed", source_url=None, snippet="")
        h.add(file="a.pdf", folder=Path("C:/x/ger101"), move_id="1", source_key="canvas/1", **kw)
        self.assertEqual(os.path.normcase(h.source_folder("canvas/1")), os.path.normcase("C:/x/ger101"))
        h.add(file="b.pdf", folder=Path("C:/x/cs201"), move_id="2", source_key="canvas/1", **kw)
        self.assertIsNone(h.source_folder("canvas/1"))
        h.mark_undone("2")
        self.assertIsNotNone(History(self.dir).source_folder("canvas/1"))  # reloaded from disk


if __name__ == "__main__":
    unittest.main()
