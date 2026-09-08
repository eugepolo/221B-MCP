import os

from mcp_221b.executables import sherlock_command


def test_virtualenv_executable_without_path(tmp_path, monkeypatch):
    executable = tmp_path / ("sherlock.exe" if os.name == "nt" else "sherlock")
    executable.write_text("placeholder")
    executable.chmod(0o700)
    monkeypatch.setattr("mcp_221b.executables.sysconfig.get_path", lambda _: str(tmp_path))
    monkeypatch.setenv("PATH", "")
    assert sherlock_command() == str(executable)
