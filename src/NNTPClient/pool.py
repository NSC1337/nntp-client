import asyncio
import logging
import socket
from contextlib import AbstractAsyncContextManager

from . import config
from NNTPClient.connection import NNTPConnection


logger = logging.getLogger(__name__)



class NNTPError(Exception):
    pass


class NNTPSession(AbstractAsyncContextManager):
    def __init__(self, num_connections: int):
        self.workers = [Worker() for _ in range(num_connections)]

    async def __aenter__(self):
        try:
            async with asyncio.TaskGroup() as task_group:
                for worker in self.workers:
                    task_group.create_task(worker.connect())
        except BaseException:
            self.close()
            raise
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.close()

    async def download(self, articles, write_callback):
        async with asyncio.TaskGroup() as task_group:
            for worker in self.workers:
                task_group.create_task(worker.download(articles, write_callback))

    def close(self):
        for worker in self.workers:
            worker.close()


class Worker:
    def __init__(self):
        self.connection: NNTPConnection = None

    async def connect(self):
        loop = asyncio.get_running_loop()
        sock = socket.socket()
        try:
            sock.setblocking(False)
            await loop.sock_connect(sock, (config.server["url"], config.server["port"]))
        except BaseException:
            sock.close()
            raise

        connection = NNTPConnection(
                    sock.detach(), config.server["url"], config.server.get("pipeline_size", 8)
                )
        try:
            await connection.tls_handshake()
            resp = await connection.read_line()
            if resp[:3] not in (b"200", b"201"):
                raise NNTPError(resp)
            await connection.send_bytes(f"AUTHINFO USER {config.server['username']}\r\n".encode())
            resp = await connection.read_line()
            if resp[:3] != b"381":
                raise NNTPError(resp)
            await connection.send_bytes(f"AUTHINFO PASS {config.server['password']}\r\n".encode())
            resp = await connection.read_line()
            if resp[:3] != b"281":
                raise NNTPError(resp)
        except BaseException:
            connection.close()
            logger.exception("failed to establish NNTP connection")
            raise
        self.connection = connection

    async def download(self, articles, write_callback):
        await self.connection.start_downloading(articles, write_callback)

    def close(self):
        if self.connection is not None:
            self.connection.close()
