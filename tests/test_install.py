"""Exercise installation without network access or changes to the user's tools."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[1] / "install.sh"
pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX installer")


@pytest.fixture
def install_env(tmp_path):
    commands = tmp_path / "commands"
    commands.mkdir()
    home = tmp_path / "home with spaces"
    home.mkdir()
    tool_bin = tmp_path / "tool bin"
    tool_bin.mkdir()
    for name in ("sh", "uname", "mktemp", "rm"):
        executable = shutil.which(name)
        if executable is None:
            pytest.skip(f"{name} is required")
        (commands / name).symlink_to(executable)

    def executable(path, code):
        path.write_text(f"#!{sys.executable}\n" + code)
        path.chmod(0o755)

    uv = tmp_path / "mock-uv"
    executable(
        uv,
        """import json, os, sys
from pathlib import Path
with open(os.environ["INSTALL_LOG"], "a") as log:
    log.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:3] == ["tool", "install"]:
    sys.exit(int(os.environ.get("INSTALL_EXIT", "0")))
if sys.argv[1:] == ["tool", "dir", "--bin"]:
    print(os.environ["MOCK_TOOL_BIN"])
""",
    )
    executable(tool_bin / "yeet", 'print("yeet 0.3.1")\n')
    env = {
        **os.environ,
        "HOME": str(home),
        "PATH": str(commands),
        "UV_INSTALL_DIR": str(home / ".local/bin"),
        "INSTALL_LOG": str(tmp_path / "calls.jsonl"),
        "MOCK_TOOL_BIN": str(tool_bin),
        "MOCK_UV": str(uv),
    }

    def run(*args):
        return subprocess.run(
            [str(commands / "sh"), str(INSTALLER), *args],
            check=False,
            env=env,
            capture_output=True,
            text=True,
        )

    return commands, uv, env, run, executable


def test_existing_uv_installs_and_checks_command(install_env):
    commands, uv, env, run, _ = install_env
    (commands / "uv").symlink_to(uv)
    result = run()
    assert result.returncode == 0, result.stderr
    calls = [
        json.loads(line) for line in Path(env["INSTALL_LOG"]).read_text().splitlines()
    ]
    assert calls[0] == [
        "tool",
        "install",
        "--python",
        "3.12",
        "--upgrade",
        "https://github.com/sohanmanju/yeet/archive/refs/heads/master.zip",
    ]
    assert calls[1:] == [["tool", "update-shell"], ["tool", "dir", "--bin"]]
    assert "yeet 0.3.1" in result.stdout
    assert "Installed!" in result.stdout


def test_uv_outside_path_and_local_source(install_env):
    _, uv, env, run, _ = install_env
    uv_dir = Path(env["UV_INSTALL_DIR"])
    uv_dir.mkdir(parents=True)
    (uv_dir / "uv").symlink_to(uv)
    result = run("/a checkout with spaces")
    assert result.returncode == 0, result.stderr
    call = json.loads(Path(env["INSTALL_LOG"]).read_text().splitlines()[0])
    assert call[-1] == "/a checkout with spaces"


def test_bootstraps_uv(install_env):
    commands, _, env, run, executable = install_env
    executable(
        commands / "curl",
        """import os, sys
from pathlib import Path
assert sys.argv[1:3] == ["-fsSL", "https://astral.sh/uv/install.sh"]
Path(sys.argv[sys.argv.index("-o") + 1]).write_text(
    'test "$UV_NO_MODIFY_PATH" = 1 || exit 1\\n'
    'mkdir -p "$UV_INSTALL_DIR"\\n'
    'cp "$MOCK_UV" "$UV_INSTALL_DIR/uv"\\n'
)
""",
    )
    for name in ("mkdir", "cp"):
        (commands / name).symlink_to(shutil.which(name))
    result = run()
    assert result.returncode == 0, result.stderr
    assert (Path(env["UV_INSTALL_DIR"]) / "uv").is_file()
    assert "Installed!" in result.stdout


def test_failed_download_does_not_install(install_env):
    commands, _, env, run, executable = install_env
    executable(commands / "curl", "raise SystemExit(22)\n")
    result = run()
    assert result.returncode == 22
    assert not Path(env["INSTALL_LOG"]).exists()
    assert "Installed!" not in result.stdout


def test_failed_install_does_not_report_success(install_env):
    commands, uv, env, run, _ = install_env
    (commands / "uv").symlink_to(uv)
    env["INSTALL_EXIT"] = "1"
    result = run()
    assert result.returncode == 1
    assert "Installed!" not in result.stdout
    assert len(Path(env["INSTALL_LOG"]).read_text().splitlines()) == 1


def test_help_needs_no_dependencies(install_env):
    _, _, env, run, _ = install_env
    result = run("--help")
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert not Path(env["INSTALL_LOG"]).exists()
