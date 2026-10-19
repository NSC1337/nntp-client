"""Measure client CPU seconds and received decimal gigabits over TLS."""

import argparse
import asyncio
from importlib import import_module
import multiprocessing as mp
import os
from pathlib import Path
import socket
import ssl
import time

HERE = Path(__file__).resolve().parent
CERTIFICATE = HERE / "localhost.crt"
PRIVATE_KEY = HERE / "localhost.key"
CASES = (
    ("asyncio", "asyncio_protocol", False),
    ("asyncio-uvloop", "asyncio_protocol", True),
    ("cython-openssl", "cython_openssl", False),
    ("cython-openssl-uvloop", "cython_openssl", True),
)


def serve(port_pipe, core):
    os.sched_setaffinity(0, {core})
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(CERTIFICATE, PRIVATE_KEY)
    block = bytes(1024 * 1024)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port_pipe.send(listener.getsockname()[1])
        port_pipe.close()
        conn, _ = listener.accept()
        with conn:
            try:
                with context.wrap_socket(conn, server_side=True) as tls:
                    while True:
                        tls.sendall(block)
            except OSError:
                pass  # The client closes the stream when measurement ends.


async def receive_for(receiver, seconds):
    done, _ = await asyncio.wait([receiver.closed], timeout=seconds)
    if done:
        raise receiver.closed.result()


async def measure(connect, port, warmup, duration):
    async with connect(port, CERTIFICATE) as receiver:
        await receive_for(receiver, warmup)
        start_bytes = receiver.received
        start_cpu = time.process_time()
        start_wall = time.perf_counter()
        await receive_for(receiver, duration)
        wall = time.perf_counter() - start_wall
        cpu = time.process_time() - start_cpu
        gigabits = (receiver.received - start_bytes) * 8 / 1e9
        return cpu, wall, gigabits


def run_client(case, port, core, warmup, duration):
    os.sched_setaffinity(0, {core})
    name, module, use_uvloop = case
    connect = import_module(module).connect
    loop_factory = asyncio.new_event_loop
    if use_uvloop:
        import uvloop
        loop_factory = uvloop.new_event_loop
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        cpu, wall, gigabits = runner.run(measure(connect, port, warmup, duration))
    print(
        f"{name}: {cpu:.3f} CPU seconds, {gigabits:.3f} gigabits, "
        f"{gigabits / wall:.3f} Gbit/s wall, {gigabits / cpu:.3f} Gbit/s CPU",
        flush=True,
    )


def run_case(processes, case, server_core, client_core, warmup, duration):
    port_pipe, server_pipe = processes.Pipe(duplex=False)
    server = processes.Process(target=serve, args=(server_pipe, server_core))
    server.start()
    server_pipe.close()
    try:
        port = port_pipe.recv()
        client = processes.Process(
            target=run_client, args=(case, port, client_core, warmup, duration),
        )
        client.start()
        try:
            client.join()
        finally:
            if client.is_alive():
                client.terminate()
                client.join()
        if client.exitcode:
            raise RuntimeError(f"{case[0]} client failed (exit {client.exitcode})")
    finally:
        port_pipe.close()
        server.terminate()
        server.join()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cores", nargs=2, type=int, required=True, metavar=("SERVER", "CLIENT"))
    parser.add_argument("--warmup", type=float, default=10)
    parser.add_argument("--duration", type=float, default=30)
    args = parser.parse_args()
    server_core, client_core = args.cores
    processes = mp.get_context("spawn")
    for case in CASES:
        run_case(processes, case, server_core, client_core, args.warmup, args.duration)


if __name__ == "__main__":
    main()
