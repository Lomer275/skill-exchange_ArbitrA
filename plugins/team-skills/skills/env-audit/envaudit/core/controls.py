from collections.abc import Callable
from pathlib import Path
import shutil
import tempfile

from .context import Context


def positive_control(
    section: str,
    name: str,
    ctx: Context,
    build: Callable[[Path], None],
    probe: Callable[[Path], int],
) -> str:
    del name
    temp_dir = Path(tempfile.mkdtemp(prefix="env-audit-ctl-"))
    try:
        build(temp_dir)
        return "pass" if probe(temp_dir) > 0 else "fail"
    except Exception:
        ctx.error(section, "positive_control_error")
        return "fail"
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
