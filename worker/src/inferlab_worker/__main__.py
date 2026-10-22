"""Operator-only polling command. No HTTP server, shell or binary downloads."""

import argparse
import os
import secrets
import signal
from pathlib import Path
from threading import Event

from sqlalchemy.exc import SQLAlchemyError

from inferlab_api.database.session import create_database_engine, session_factory

from .contracts import WorkerPolicy
from .locking import WorkerAlreadyRunning
from .processes import ProcessBackend
from .service import Worker
from .store import WorkerStore


def main() -> None:
    parser = argparse.ArgumentParser(description="InferLab private local database worker")
    parser.add_argument("--once", action="store_true", help="Poll once, including recovery")
    parser.add_argument(
        "--resume", action="store_true", help="Resume a paused queue after stop verification"
    )
    args = parser.parse_args()
    policy_path = os.getenv("INFERLAB_WORKER_POLICY_FILE")
    factory = os.getenv("INFERLAB_RUNNER_FACTORY")
    if not policy_path and not factory:
        print("InferLab worker: not configured. No jobs were claimed or executed.")
        return
    if not policy_path or not factory:
        parser.error("Both a private policy file and a trusted runner factory are required")
    stop = Event()

    def request_stop(signum: int, frame: object) -> None:
        stop.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    engine = None
    try:
        path = Path(policy_path)
        if path.stat().st_size > 262144:
            raise ValueError("Oversized policy")
        policy = WorkerPolicy.model_validate_json(path.read_bytes())
        backend = ProcessBackend(factory)
        engine = create_database_engine()
        store = WorkerStore(session_factory(engine), policy)
        lock_path = Path(
            os.getenv("INFERLAB_GPU_LOCK_FILE", str(Path.home() / ".inferlab-gpu.lock"))
        )
        worker = Worker(store, backend, "worker-" + secrets.token_hex(12), lock_path)
        worker.serve(stop, once=args.once, resume=args.resume)
    except WorkerAlreadyRunning:
        parser.exit(1, "InferLab worker: another local process owns the GPU lock.\n")
    except (ValueError, OSError):
        parser.exit(
            1, "InferLab worker: invalid/unavailable local configuration; no result accepted.\n"
        )
    except (SQLAlchemyError, RuntimeError):
        parser.exit(1, "InferLab worker: storage unavailable; migrate/restore before restarting.\n")
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    main()
