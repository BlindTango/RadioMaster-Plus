"""Stream separate video/audio through FFmpeg without a complete download."""

import logging
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from radiomaster.utils.network import get_ffplay_http_proxy_env, get_ffmpeg_input_args
from radiomaster.utils.tools import get_ffmpeg

log = logging.getLogger("radiomaster")


class VideoStream:
    """Own a loopback stream and its bounded FFmpeg subprocess lifetime."""

    def __init__(self, inputs: dict):
        self.inputs = inputs
        self._lock = threading.Lock()
        self._closed = False
        self._process = None
        self._server = None

    def _command(self) -> list[str]:
        command = [get_ffmpeg(), "-nostdin", "-hide_banner", "-loglevel", "error"]
        for kind in ("video", "audio"):
            command.extend(get_ffmpeg_input_args())
            headers = self.inputs.get(f"{kind}_headers") or {}
            if headers:
                value = "".join(f"{key}: {value}\r\n" for key, value in headers.items())
                command.extend(["-headers", value])
            command.extend(["-i", self.inputs[f"{kind}_url"]])
        command.extend(["-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
                        "-f", "matroska", "-flush_packets", "1", "pipe:1"])
        return command

    def start(self) -> str:
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_GET(self):
                if self.path != "/stream":
                    self.send_error(404)
                    return
                with tempfile.TemporaryFile() as errors:
                    with owner._lock:
                        if owner._closed or owner._process is not None:
                            self.send_error(410)
                            return
                        import os
                        environment = os.environ.copy()
                        environment.update(get_ffplay_http_proxy_env())
                        process = owner._process = subprocess.Popen(
                            owner._command(), stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE, stderr=errors, env=environment,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                    self.send_response(200)
                    self.send_header("Content-Type", "video/x-matroska")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    try:
                        while chunk := process.stdout.read1(65536):
                            self.wfile.write(chunk)
                        if process.wait(timeout=2) and not owner._closed:
                            errors.seek(0)
                            log.warning("Video stream could not be combined: %s",
                                        errors.read(4096).decode("utf-8", errors="replace"))
                    except (BrokenPipeError, ConnectionResetError, OSError,
                            subprocess.TimeoutExpired):
                        pass
                    finally:
                        owner._terminate()
                        process.stdout.close()

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever,
                         kwargs={"poll_interval": 0.1}, daemon=True,
                         name="video-stream").start()
        return f"http://127.0.0.1:{self._server.server_port}/stream"

    def _terminate(self):
        with self._lock:
            process = self._process
            if process is not None and process.poll() is None:
                process.kill()

    def close(self):
        self._closed = True
        self._terminate()
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
