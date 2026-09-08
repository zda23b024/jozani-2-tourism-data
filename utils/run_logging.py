import os
import sys
from datetime import datetime
from pathlib import Path
from typing import TextIO


NOISY_CONSOLE_PREFIXES = (
    "Search URL:",
    "Attractions URL:",
    "Destination ID:",
    "Date mode:",
    "Check-in date:",
    "Check-out date:",
    "  request_url:",
    "  method:",
    "  operation:",
    "  query_id:",
    "  variable_keys:",
    "  original_pagination:",
    "  replay_pagination:",
    "Response Content-Type:",
)


def concise_console_line(message: str) -> bool:
    if message.strip() == "":
        return True
    if "VERBOSE_LOGS" in os.environ and os.environ["VERBOSE_LOGS"].lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True
    return not message.lstrip().startswith(NOISY_CONSOLE_PREFIXES)


class TeeStream:
    def __init__(self, console: TextIO, log_file: TextIO) -> None:
        self.console = console
        self.log_file = log_file

    def write(self, message: str) -> int:
        if concise_console_line(message):
            self.console.write(message)
        self.log_file.write(message)
        return len(message)

    def flush(self) -> None:
        self.console.flush()
        self.log_file.flush()


class RunLogger:
    def __init__(self, log_dir: Path) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = log_dir / f"booking_run_{timestamp}.log"
        self._log_file: TextIO | None = None
        self._stdout: TextIO | None = None
        self._stderr: TextIO | None = None

    def __enter__(self) -> Path:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_file = self.log_path.open("w", encoding="utf-8")
        self._stdout = sys.stdout
        self._stderr = sys.stderr
        sys.stdout = TeeStream(self._stdout, self._log_file)  # type: ignore[assignment]
        sys.stderr = TeeStream(self._stderr, self._log_file)  # type: ignore[assignment]
        print(f"Run log: {self.log_path}")
        return self.log_path

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._stdout is not None:
            sys.stdout = self._stdout
        if self._stderr is not None:
            sys.stderr = self._stderr
        if self._log_file is not None:
            self._log_file.close()
