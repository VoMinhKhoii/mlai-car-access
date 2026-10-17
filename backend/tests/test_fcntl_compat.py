"""The portable flock shim keeps flock semantics on every platform (Windows has no fcntl)."""
import tempfile
import unittest
from pathlib import Path

from app import fcntl_compat as fcntl


class FlockTests(unittest.TestCase):
    def test_exclusive_lock_excludes_second_handle_until_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state.lock"
            with path.open("a+") as first:
                fcntl.flock(first, fcntl.LOCK_EX)
                with path.open("a+") as second, self.assertRaises(BlockingIOError):
                    fcntl.flock(second, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with path.open("a+") as third:  # closing the holder released the lock
                fcntl.flock(third, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_locked_file_content_stays_readable_and_position_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rate.lock"
            path.write_text("1792210770")
            with path.open("a+") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX)
                handle.seek(0)
                self.assertEqual(handle.read(), "1792210770")
                self.assertEqual(path.read_text(), "1792210770")  # another handle can still read


if __name__ == "__main__":
    unittest.main()
