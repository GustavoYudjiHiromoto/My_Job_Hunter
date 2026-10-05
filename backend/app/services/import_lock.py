import os
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy.orm import Session

_LOCAL_LOCKS: dict[str, threading.Lock] = {}
_LOCAL_LOCKS_GUARD = threading.Lock()


class ImportAlreadyRunning(RuntimeError):
    """Raised when another collection already owns the local import lock."""


def _lock_path(db: Session) -> Path:
    url = db.get_bind().url
    database = url.database
    if database and database != ":memory:":
        database_path = Path(database).resolve()
        return database_path.with_suffix(database_path.suffix + ".import.lock")
    return Path(tempfile.gettempdir()) / f"job-hunter-{id(db.get_bind())}.import.lock"


def _local_lock(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _LOCAL_LOCKS_GUARD:
        return _LOCAL_LOCKS.setdefault(key, threading.Lock())


@contextmanager
def import_lock(db: Session) -> Iterator[None]:
    """Lock imports across API threads and processes on the same machine."""
    path = _lock_path(db)
    path.parent.mkdir(parents=True, exist_ok=True)
    local_lock = _local_lock(path)
    if not local_lock.acquire(blocking=False):
        raise ImportAlreadyRunning

    handle = None
    unlock = None
    locked = False
    try:
        handle = path.open("a+b")
        if os.name == "nt":
            import msvcrt

            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise ImportAlreadyRunning from error

            def unlock():
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise ImportAlreadyRunning from error

            def unlock():
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

        locked = True
        yield
    finally:
        try:
            if locked and unlock is not None:
                unlock()
        finally:
            try:
                if handle is not None:
                    handle.close()
            finally:
                local_lock.release()
