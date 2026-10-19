"""Receive TLS data into a reusable 1 MiB buffer."""

import asyncio
from contextlib import asynccontextmanager
import ssl


class Receiver(asyncio.BufferedProtocol):
    def __init__(self):
        self.buffer = bytearray(1024 * 1024)
        self.received = 0
        self.closed = asyncio.get_running_loop().create_future()

    def get_buffer(self, sizehint):
        return self.buffer

    def buffer_updated(self, nbytes):
        self.received += nbytes

    def connection_lost(self, exc):
        if not self.closed.done():
            self.closed.set_result(exc or ConnectionError("TLS stream closed"))


@asynccontextmanager
async def connect(port, certificate):
    context = ssl.create_default_context(cafile=str(certificate))
    receiver = Receiver()
    transport, _ = await asyncio.get_running_loop().create_connection(
        lambda: receiver, "127.0.0.1", port,
        ssl=context, server_hostname="localhost",
    )
    try:
        yield receiver
    finally:
        transport.abort()
