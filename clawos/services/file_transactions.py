"""Bounded text writes with a cross-process compare-and-swap boundary.

The tool security policy remains responsible for allowed roots. Locks coordinate
ClawOS writers; unrelated editors must also use a lock to guarantee mutual exclusion.
"""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import tempfile
import time


@contextmanager
def _file_lock(target, timeout=10, *, lock_dir=None):
    # Keep a stable lock inode: deleting it after release races waiting writers.
    folder = Path(lock_dir) if lock_dir is not None else Path(tempfile.gettempdir()) / "clawos-file-locks"
    folder.mkdir(parents=True,exist_ok=True)
    key = hashlib.sha256(os.path.normcase(str(target)).encode()).hexdigest()
    with (folder / (key + ".lock")).open("a+b") as handle:
        # Windows permits byte-range locks past EOF. Initializing a byte before
        # acquiring the lock races another handle already locking the empty
        # file, causing PermissionError at flush rather than bounded contention.
        deadline = time.monotonic() + timeout
        while True:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("file is busy; retry the write")
                time.sleep(.02)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def write_text(path, content, *, append=False, expected_sha256="", create_only=False,
               preview=False, max_bytes=8 * 1024 * 1024):
    target = Path(path).resolve()
    data = str(content).encode("utf-8")
    if len(data) > max_bytes:
        raise ValueError("text exceeds the 8 MiB file limit")
    with _file_lock(target):
        exists = target.exists()
        if exists and (not target.is_file() or target.stat().st_size > max_bytes):
            raise ValueError("target must be a text file within the 8 MiB limit")
        before = target.read_bytes() if exists else b""
        digest = hashlib.sha256(before).hexdigest()
        if create_only and exists:
            raise ValueError("write conflict: create_only target already exists")
        if expected_sha256 and expected_sha256 != digest:
            raise ValueError("write conflict: expected_sha256 does not match current file")
        if append:
            before.decode("utf-8")  # Reject binary input rather than corrupting it.
            data = before + data
        if len(data) > max_bytes:
            raise ValueError("text exceeds the 8 MiB file limit")
        result = dict(path=str(target), size_bytes=len(data), append=bool(append),
                      before_sha256=digest, sha256=hashlib.sha256(data).hexdigest(),
                      atomic=True, concurrency="cooperating-process-lock", preview=bool(preview))
        if preview:
            return dict(result, written=False, exists=exists)
        target.parent.mkdir(parents=True, exist_ok=True)
        # A digest-named target can fit Windows MAX_PATH while copying its
        # entire basename into the temporary name exceeds it. The random
        # sibling is already unique; replacement still occurs on one volume.
        descriptor, name = tempfile.mkstemp(prefix=".claw-", suffix=".tmp", dir=target.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return dict(result, written=True, exists=True)
