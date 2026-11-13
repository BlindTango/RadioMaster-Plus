"""The watchdog records the blocking call when the window stops responding.

Each scenario runs in its own process: a real wx event loop (timers only fire
inside one) cannot safely share a process with the other tests' wx.App objects.
"""

import os
import subprocess
import sys
import textwrap

SCRIPT = textwrap.dedent('''
    import sys, time
    import wx
    from radiomaster.utils.ui_watchdog import UiWatchdog

    log_dir, scenario = sys.argv[1], sys.argv[2]
    app = wx.App(False)
    dog = UiWatchdog(log_dir, threshold=0.6, interval_ms=50)
    dog.start()

    def slow_handler_blocking_the_ui():
        time.sleep(1.6)

    loop = wx.GUIEventLoop()
    with wx.EventLoopActivator(loop):
        if scenario == "blocked":
            wx.CallLater(500, slow_handler_blocking_the_ui)
        wx.CallLater(5000 if scenario == "blocked" else 2000, loop.Exit)
        loop.Run()
    dog.stop()
''')


def run(tmp_path, scenario):
    env = dict(os.environ)
    src = os.path.join(os.path.dirname(__file__), "..", "src")
    env["PYTHONPATH"] = os.path.abspath(src) + os.pathsep + env.get("PYTHONPATH", "")
    subprocess.run([sys.executable, "-c", SCRIPT, str(tmp_path), scenario],
                   check=True, env=env, timeout=60, capture_output=True)
    path = tmp_path / "ui-stalls.log"
    return path.read_text(encoding="utf-8") if path.exists() else None


def test_a_healthy_ui_is_never_reported(tmp_path):
    assert run(tmp_path, "healthy") is None


def test_a_blocked_ui_thread_is_reported_with_its_stack(tmp_path):
    report = run(tmp_path, "blocked")
    assert report is not None
    assert "UI thread not responding" in report
    assert "--- UI THREAD ---" in report
    assert "slow_handler_blocking_the_ui" in report          # the call the window was stuck in
    assert report.count("=== UI thread not responding") == 1  # once per stall
    assert "UI responsive again" in report
