from pathlib import Path

import pytest

from envaudit.core.runner import run, which
from envaudit.secrets.sshkeys import key_info


def test_encrypted_detection(tmp_path: Path):
    executable = which("ssh-keygen")
    if executable is None:
        pytest.skip("ssh-keygen is not installed")
    plain = tmp_path / "plain"
    protected = tmp_path / "protected"
    assert run([executable, "-q", "-t", "ed25519", "-N", "", "-f", str(plain)]).rc == 0
    phrase = "pass" + "-phrase-x"
    assert run([executable, "-q", "-t", "ed25519", "-N", phrase, "-f", str(protected)]).rc == 0
    plain.chmod(0o644)
    protected.chmod(0o600)
    plain_info = key_info(plain)
    protected_info = key_info(protected)
    assert plain_info["encrypted"] is False
    assert protected_info["encrypted"] is True
    assert plain_info["mode"] == "0644"
    assert plain_info["wider_than_600"] is True
    assert protected_info["mode"] == "0600"
    assert protected_info["wider_than_600"] is False
