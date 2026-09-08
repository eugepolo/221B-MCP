"""Find optional commands even when a GUI client has not activated the virtualenv."""

import os
import shutil
import sysconfig
from pathlib import Path


def sherlock_command() -> str | None:
    executable = Path(sysconfig.get_path("scripts")) / (
        "sherlock.exe" if os.name == "nt" else "sherlock"
    )
    if executable.is_file() and os.access(executable, os.X_OK):
        return str(executable)
    return shutil.which("sherlock")
