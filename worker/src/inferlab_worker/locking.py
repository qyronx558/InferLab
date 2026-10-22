"""Host-local OS lock. Never delete the lock file: that would split ownership."""

import sys
from pathlib import Path
from types import TracebackType
from typing import BinaryIO


class WorkerAlreadyRunning(Exception):
    pass


class GPULock:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.file: BinaryIO | None = None

    def __enter__(self) -> "GPULock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        file = self.path.open("a+b")
        try:
            file.seek(0)
            if not file.read(1):
                file.write(b"\0")
                file.flush()
            file.seek(0)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            file.close()
            raise WorkerAlreadyRunning("Another worker owns the GPU lock") from None
        self.file = file
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.file is not None:
            # Closing the handle releases the OS lock, including after parent death.
            self.file.close()
            self.file = None
