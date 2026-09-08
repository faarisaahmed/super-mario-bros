"""
Local launcher for Super Mario Bros AI.

Serves index.html (the Play / Train menu) and, because PyTorch-based training
cannot run inside a browser, drives the real native processes on this machine:

  Play  -> python main.py           (the normal game, keyboard/controller)
  Train -> python train_ai.py       (trains PPO, saves the best model)
           then automatically:
           python watch_ai.py       (the best model plays, in its own window)

Run it with:   python3 server.py
Then open:     http://localhost:8000
"""

import os
import sys
import json
import threading
import subprocess
import http.server
import socketserver

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
PORT = 8000

# How many timesteps a Train run targets (kept in sync with train_ai.py so we
# can show a progress bar). Overridable with the same env var.
TIMESTEPS = int(os.environ.get("MARIO_TIMESTEPS", 2_000_000))

# Shared launcher state, guarded by a lock.
_lock = threading.Lock()
state = {
    "mode": "idle",          # idle | playing | training | watching | error | stopped
    "stats": {},             # latest SB3 metrics parsed from training output
    "target": TIMESTEPS,     # total timesteps this run is aiming for
}
_procs = {}                       # keep handles so we don't garbage-collect them


def _headless_env():
    """Env for the training process — no window, no audio."""
    env = os.environ.copy()
    env["SDL_VIDEODRIVER"] = "dummy"
    env["SDL_AUDIODRIVER"] = "dummy"
    env["PYTHONUNBUFFERED"] = "1"   # stream metric lines to us promptly
    return env


def _spawn(script, env=None, capture=False):
    return subprocess.Popen(
        [sys.executable, script],
        cwd=PROJECT_DIR,
        env=env or os.environ.copy(),
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        text=True,
        bufsize=1,
    )


def _parse_training_output(proc):
    """Read the training process' stdout and turn SB3's printed metric tables
    into a live dict on state['stats']. SB3 prints blocks like:

        -----------------------------
        | rollout/           |       |
        |    ep_rew_mean     | 196   |
        |    total_timesteps | 8192  |
        -----------------------------
    """
    block = {}
    for line in proc.stdout:
        line = line.rstrip("\n")
        stripped = line.strip()
        # A divider row (all dashes) closes the current block.
        if stripped and set(stripped) <= {"-"}:
            if block:
                with _lock:
                    state["stats"] = block
                block = {}
            continue
        if line.startswith("|"):
            parts = [p.strip() for p in line.split("|")]
            if len(parts) >= 3:
                key, val = parts[1], parts[2]
                if key and val:            # skip section headers (blank value)
                    block[key.split("/")[-1]] = val


def _best_model_path():
    """Path (without .zip) of the model the watcher will use, or None if there
    is no trained model on disk yet. Prefers the best checkpoint; falls back to
    the final save — this is also the 'best so far' after an early Stop."""
    if os.path.exists(os.path.join(PROJECT_DIR, "best_model", "best_model.zip")):
        return "best_model/best_model"
    if os.path.exists(os.path.join(PROJECT_DIR, "mario_model.zip")):
        return "mario_model"
    return None


def _run_play():
    with _lock:
        if state["mode"] in ("training", "watching"):
            return  # don't interrupt a training run
        state["mode"] = "playing"
    _procs["play"] = _spawn("main.py")


def _run_watch():
    """Launch the best trained model in its own window, on demand."""
    with _lock:
        if state["mode"] == "training":
            return "training"          # don't start a watcher mid-training
    if _best_model_path() is None:
        return "no_model"              # nothing trained yet
    with _lock:
        state["mode"] = "watching"
    _procs["watch"] = _spawn("watch_ai.py")
    return "ok"


def _train_then_watch():
    """Background worker: train to completion, then launch the watcher."""
    try:
        train = _spawn("train_ai.py", env=_headless_env(), capture=True)
        _procs["train"] = train
        _parse_training_output(train)   # blocks until the pipe closes (process ends)
        code = train.wait()
        with _lock:
            stopped = state["mode"] == "stopped"
        if stopped:
            return                       # user hit Stop; leave mode as 'stopped'
        if code != 0:
            with _lock:
                state["mode"] = "error"
            return
        with _lock:
            state["mode"] = "watching"
        _procs["watch"] = _spawn("watch_ai.py")
    except Exception:
        with _lock:
            state["mode"] = "error"


def _run_train():
    with _lock:
        if state["mode"] == "training":
            return
        state["mode"] = "training"
        state["stats"] = {}
    threading.Thread(target=_train_then_watch, daemon=True).start()


def _stop_train():
    """Terminate a running training process and reset to idle."""
    with _lock:
        was_training = state["mode"] == "training"
        state["mode"] = "stopped"
    proc = _procs.get("train")
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    return was_training


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True   # avoid "address already in use" on quick restarts


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=PROJECT_DIR, **kwargs)

    def _json(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.path = "/index.html"
            return super().do_GET()
        if self.path == "/status":
            with _lock:
                return self._json(dict(state))
        return super().do_GET()

    def do_POST(self):
        if self.path == "/play":
            _run_play()
            return self._json({"ok": True, "mode": "playing"})
        if self.path == "/watch":
            result = _run_watch()
            return self._json({"ok": result == "ok", "result": result})
        if self.path == "/train":
            _run_train()
            with _lock:
                return self._json({"ok": True, "mode": state["mode"]})
        if self.path == "/stop":
            _stop_train()
            return self._json({"ok": True, "mode": "stopped"})
        self._json({"error": "unknown endpoint"}, code=404)

    def log_message(self, *args):
        pass  # keep the console quiet


if __name__ == "__main__":
    os.chdir(PROJECT_DIR)
    with Server(("", PORT), Handler) as httpd:
        print(f"Super Mario Bros AI launcher running at http://localhost:{PORT}")
        print("Press Ctrl+C to stop.")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down.")
