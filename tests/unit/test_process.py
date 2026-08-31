import sys

from ewp_waveform.ffmpeg.process import run_argv_stdin


def test_run_argv_stdin_does_not_deadlock_on_chatty_stderr() -> None:
    script = (
        "import sys\n"
        "n = 0\n"
        "while True:\n"
        "    block = sys.stdin.buffer.read(65536)\n"
        "    if not block:\n"
        "        break\n"
        "    n += len(block)\n"
        "    sys.stderr.buffer.write(b'x' * 200000)\n"
        "    sys.stderr.buffer.flush()\n"
        "sys.stdout.buffer.write(str(n).encode())\n"
    )
    payload = [b"a" * 8192 for _ in range(80)]
    completed = run_argv_stdin([sys.executable, "-c", script], payload)
    assert completed.returncode == 0
    assert completed.stdout == str(8192 * 80).encode()
    assert len(completed.stderr) >= 200000
