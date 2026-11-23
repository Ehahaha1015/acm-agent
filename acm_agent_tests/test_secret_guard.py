import subprocess
import sys
from pathlib import Path

CHECKER = Path(__file__).resolve().parents[1] / "scripts" / "check_secrets.py"


def test_guard_blocks_forced_env_file_without_printing_secret(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    secret = "synthetic-secret-for-test-only"
    (tmp_path / ".env").write_text(f"DEEPSEEK_API_KEY={secret}\n")
    subprocess.run(["git", "add", "-f", ".env"], cwd=tmp_path, check=True)
    result = subprocess.run([sys.executable, str(CHECKER)], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "BLOCKED: .env" in result.stdout
    assert secret not in result.stdout + result.stderr


def test_guard_blocks_key_copied_into_source(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    secret = "sk-" + "synthetic1234567890" * 2
    (tmp_path / "app.py").write_text(f"KEY = '{secret}'\n")
    subprocess.run(["git", "add", "app.py"], cwd=tmp_path, check=True)
    result = subprocess.run([sys.executable, str(CHECKER)], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    assert "BLOCKED: app.py" in result.stdout
    assert secret not in result.stdout + result.stderr


def test_guard_allows_empty_environment_template(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".env.example").write_text("DEEPSEEK_API_KEY=\nDEEPSEEK_MODEL=deepseek-flash\n")
    subprocess.run(["git", "add", ".env.example"], cwd=tmp_path, check=True)
    result = subprocess.run([sys.executable, str(CHECKER), "--all"], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 0
