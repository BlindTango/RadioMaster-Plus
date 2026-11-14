"""A YouTube video must play to its end even when the server drops the connection.

googlevideo.com closes long and idle connections part-way. This serves media from
a local server that does the same (200 KB per connection, Range supported) and
checks how far the combined stream gets.
"""

import os
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from radiomaster.services.video_stream import RECONNECT_ARGS, VideoStream
from radiomaster.utils.tools import get_ffmpeg

SECONDS = 30
CUT = 200_000


@pytest.fixture(scope="module")
def media(tmp_path_factory):
    ffmpeg = get_ffmpeg()
    if not ffmpeg or not os.path.exists(ffmpeg):
        pytest.skip("ffmpeg is not available")
    folder = tmp_path_factory.mktemp("media")
    video, audio = str(folder / "v.mkv"), str(folder / "a.mka")
    quiet = [ffmpeg, "-hide_banner", "-loglevel", "error"]
    subprocess.run(quiet + ["-f", "lavfi", "-i", "testsrc=size=320x240:rate=15", "-t", str(SECONDS),
                            "-c:v", "libx264", "-b:v", "600k", "-an", video], check=True)
    subprocess.run(quiet + ["-f", "lavfi", "-i", "sine=frequency=440", "-t", str(SECONDS),
                            "-c:a", "libopus", "-b:a", "64k", audio], check=True)
    return {"/v": video, "/a": audio}


@pytest.fixture
def flaky_server(media):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def do_GET(self):
            with open(media[self.path], "rb") as fh:
                data = fh.read()
            match = re.match(r"bytes=(\d+)-", self.headers.get("Range", ""))
            start = int(match.group(1)) if match else 0
            body = data[start:]
            self.send_response(206 if match else 200)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(len(body)))
            if match:
                self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
            self.end_headers()
            try:
                self.wfile.write(body[:CUT])
                self.wfile.flush()
            except OSError:
                pass
            self.close_connection = True      # the rest is never sent

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def reached_seconds(command):
    command = command[:command.index("-f")] + ["-f", "null", "-"]
    command[command.index("error")] = "info"
    result = subprocess.run(command, capture_output=True, text=True, timeout=120)
    times = re.findall(r"time=(\d+):(\d+):([\d.]+)", result.stderr)
    if not times:
        return 0.0
    hours, minutes, seconds = times[-1]
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def without_reconnect(command):
    flags = set(RECONNECT_ARGS[0::2])
    out, i = [], 0
    while i < len(command):
        if command[i] in flags and i + 1 < len(command):
            i += 2
            continue
        out.append(command[i])
        i += 1
    return out


def test_video_plays_to_the_end_when_the_connection_is_dropped(flaky_server):
    command = VideoStream({"video_url": flaky_server + "/v", "audio_url": flaky_server + "/a"})._command()
    assert reached_seconds(command) >= SECONDS - 1


def test_the_same_drops_end_the_video_early_without_reconnect(flaky_server):
    """Guards the test above: the simulated server really does cut the stream short."""
    command = VideoStream({"video_url": flaky_server + "/v", "audio_url": flaky_server + "/a"})._command()
    assert reached_seconds(without_reconnect(command)) < SECONDS - 5
