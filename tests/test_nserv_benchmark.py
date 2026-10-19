"""End-to-end benchmark against NServ.

Run with:
    uv run pytest -s tests/test_nserv_benchmark.py

The first pass writes and verifies the downloaded file. The timed pass uses the
same warm NServ in-memory cache, but replaces the downloader's write callback
with a no-op so its result is not distorted by filesystem writes.
"""

import asyncio
import gc
import hashlib
import importlib
import os
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path
from types import ModuleType

from NNTPClient.main import parse_nzb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MOVIE = PROJECT_ROOT / "movie.mkv"
SEGMENT_SIZE = 16 * 1024 * 1024
PIPELINE_SIZE = 2


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_affinity(process: subprocess.Popen[bytes], cpu: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read().decode(errors="replace") if process.stderr else ""
            raise AssertionError(f"NServ exited during startup: {stderr}")
        if os.sched_getaffinity(process.pid) == {cpu}:
            return
        time.sleep(0.01)
    raise AssertionError(f"NServ did not start pinned to CPU {cpu}")


def _wait_for_listener(process: subprocess.Popen[bytes], port: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read().decode(errors="replace") if process.stderr else ""
            raise AssertionError(f"NServ exited during startup: {stderr}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                return
        except ConnectionRefusedError:
            time.sleep(0.01)
    raise AssertionError(f"NServ did not listen on port {port}")


def _write_nzb(nzb: Path) -> None:
    """Write NServ message IDs without its 32-bit-limited NZB generator."""
    segments = []
    for number, offset in enumerate(range(0, MOVIE.stat().st_size, SEGMENT_SIZE), start=1):
        size = min(SEGMENT_SIZE, MOVIE.stat().st_size - offset)
        segments.append(
            f'<segment bytes="{size}" number="{number}">'
            f'movie.mkv?{number}={offset}:{size}</segment>'
        )
    nzb.write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">\n'
        '<file poster="nserv" date="0" subject="movie.mkv">\n'
        '<groups><group>alt.binaries.test</group></groups>\n<segments>\n'
        + "\n".join(segments)
        + "\n</segments></file></nzb>\n",
        encoding="utf-8",
    )


def _make_certificate(cert: Path, key: Path) -> None:
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
            "-keyout",
            str(key),
            "-out",
            str(cert),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


async def _download(article_ids: list[str], connection_module: ModuleType, port: int) -> None:
    loop = asyncio.get_running_loop()
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setblocking(False)
    await loop.sock_connect(sock, ("localhost", port))

    connection = connection_module.NNTPConnection(
        sock.detach(), "localhost", pipeline_size=PIPELINE_SIZE
    )
    await connection.tls_handshake()
    assert (await connection.read_line()).startswith(b"200")
    await connection.send_bytes(b"AUTHINFO USER benchmark\r\n")
    assert (await connection.read_line()).startswith(b"381")
    await connection.send_bytes(b"AUTHINFO PASS benchmark\r\n")
    assert (await connection.read_line()).startswith(b"281")

    await connection.start_downloading(article_ids.copy())
    del connection
    gc.collect()


def test_nserv_tls_benchmark(monkeypatch) -> None:
    if not MOVIE.is_file() or MOVIE.stat().st_size != 4 * 1024**3:
        raise AssertionError(f"{MOVIE} must be an exactly 4 GiB regular file")

    allowed_cpus = sorted(os.sched_getaffinity(0))
    if len(allowed_cpus) < 2:
        raise AssertionError("the benchmark requires two CPUs in this process's affinity mask")
    python_cpu, nserv_cpu = allowed_cpus[:2]
    original_affinity = os.sched_getaffinity(0)
    os.sched_setaffinity(0, {python_cpu})

    workspace = Path(tempfile.mkdtemp(prefix=".nserv-benchmark-", dir=PROJECT_ROOT))
    data_dir = workspace / "data"
    cert = workspace / "localhost.crt"
    key = workspace / "localhost.key"
    output = workspace / "downloaded-movie.mkv"
    process: subprocess.Popen[bytes] | None = None

    try:
        data_dir.mkdir()
        # A hard link lets NServ serve movie.mkv without another 4 GiB copy.
        os.link(MOVIE, data_dir / MOVIE.name)
        _make_certificate(cert, key)

        # NServ's `-z` generator overflows at 4 GiB, so construct its documented
        # message IDs here; NServ still serves every article in both passes.
        nzb = data_dir / "movie.mkv.nzb"
        _write_nzb(nzb)
        article_ids = parse_nzb(nzb).article_ids
        assert article_ids

        # NNTPConnection loads OpenSSL's default trust store during import. Pointing
        # SSL_CERT_FILE at this temporary self-signed localhost certificate keeps
        # certificate and hostname verification enabled for this test.
        monkeypatch.setenv("SSL_CERT_FILE", str(cert))
        connection_module = importlib.import_module("NNTPClient.connection")
        writer_module = importlib.import_module("NNTPClient.writer.writer")

        port = _free_port()
        command = (
            f"exec taskset --cpu-list {nserv_cpu} \\nzbget --nserv "
            f"-d {shlex.quote(str(data_dir))} -m -b 127.0.0.1 -p {port} "
            f"-s {shlex.quote(str(cert))} {shlex.quote(str(key))} -v 1"
        )
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        _wait_for_affinity(process, nserv_cpu)
        _wait_for_listener(process, port)

        # The full download is also readiness checking: it verifies the TLS
        # handshake, NServ's yEnc traffic, parser, and real writer end to end.
        writer_module.files.clear()
        asyncio.run(_download(article_ids, connection_module, port))
        writer_module.close_files()
        writer_module.files.clear()
        assert output.stat().st_size == MOVIE.stat().st_size
        assert _sha256(output) == _sha256(MOVIE)
        output.unlink()

        # The connection module imports this callback into its extension module, so
        # patch that exact reference rather than the source writer module for the timed pass.
        monkeypatch.setattr(connection_module, "write_to_disk", lambda data, filename, offset: None)
        started = time.perf_counter()
        asyncio.run(_download(article_ids, connection_module, port))
        elapsed = time.perf_counter() - started
        throughput_mib_s = MOVIE.stat().st_size / elapsed / (1024 * 1024)
        print(
            f"\nNServ TLS no-disk benchmark: {MOVIE.stat().st_size / 1024**3:.2f} GiB "
            f"in {elapsed:.3f} s ({throughput_mib_s:.2f} MiB/s); "
            f"python CPU {python_cpu}, NServ CPU {nserv_cpu}"
        )
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        os.sched_setaffinity(0, original_affinity)
        shutil.rmtree(workspace, ignore_errors=True)
