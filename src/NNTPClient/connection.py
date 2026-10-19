import asyncio
import ssl
from collections import deque
from collections.abc import Callable
from typing import Any, cast

import cython
import cython.cimports.NNTPClient.openssl as ossl

from NNTPClient.parser import ArticleState, Parser

ctx = cython.declare(cython.pointer[ossl.SSL_CTX], ossl.SSL_CTX_new(ossl.TLS_client_method()))
if ctx == cython.NULL:
    raise MemoryError("ossl.SSL_CTX_new failed")
if ossl.SSL_CTX_set_default_verify_paths(ctx) != 1:
    raise RuntimeError("failed to load the default TLS trust store")
ossl.SSL_CTX_set_verify(ctx, ossl.SSL_VERIFY_PEER, cython.NULL)
ossl.SSL_CTX_set_options(ctx, ossl.SSL_OP_ENABLE_KTLS)


@cython.final
@cython.cclass
class NNTPConnection:
    ssl: cython.pointer[ossl.SSL]
    fd: cython.int
    result: asyncio.Future[Any]
    loop: asyncio.AbstractEventLoop
    pipeline_size: cython.Py_ssize_t
    buffer: bytearray
    pipeline: deque[str]
    parser: Parser
    articles: list[str]
    command: bytes | None
    reading: cython.bint
    want_write: cython.bint
    write_callback: object

    def __init__(
        self,
        fd: cython.int,
        hostname: str,
        pipeline_size: cython.Py_ssize_t,
    ) -> None:
        """Create a TLS-protected connection to an NNTP server."""
        bio: cython.pointer[ossl.BIO]
        hostname_bytes: bytes = hostname.encode("idna")

        self.ssl = ossl.SSL_new(ctx)
        if self.ssl == cython.NULL:
            raise MemoryError("ossl.SSL_new failed")

        bio = ossl.BIO_new_socket(fd, ossl.BIO_CLOSE)
        if bio == cython.NULL:
            raise MemoryError("ossl.BIO_new_socket failed")

        self.fd = fd
        ossl.SSL_set_bio(self.ssl, bio, bio)

        if ossl.SSL_set_tlsext_host_name(self.ssl, hostname_bytes) != 1:
            raise RuntimeError("failed to configure TLS SNI")
        if ossl.SSL_set1_host(self.ssl, hostname_bytes) != 1:
            raise RuntimeError("failed to configure TLS hostname verification")

        self.loop = asyncio.get_running_loop()
        self.pipeline_size = pipeline_size
        self.buffer = bytearray(1024 * 1024)
        self.pipeline = deque()
        self.parser = Parser(self.buffer, pipeline_size)
        self.articles = []
        self.command = None
        self.reading = False
        self.want_write = False
        self.write_callback = None

    async def start_downloading(
        self,
        articles: list[str],
        write_callback: Callable[[memoryview, str, int, int, str], None],
    ) -> None:
        """Pipeline BODY requests and pass decoded article chunks to a callback."""
        self.result = self.loop.create_future()
        self.articles = articles
        self.write_callback = write_callback
        self.command = None
        self.reading = False
        self.want_write = False
        self.loop.add_reader(self.fd, self._read_parse_write)
        self._read_parse_write()
        await self.result

    def _read_parse_write(self) -> None:
        ret: cython.int
        error: cython.int
        nbytes: cython.size_t = 0
        read: cython.size_t = 0
        written: cython.size_t = 0

        if self.reading:
            while nbytes < len(self.buffer):
                read = 0
                ret = ossl.SSL_read_ex(
                    self.ssl,
                    cython.cast(cython.p_char, self.buffer) + nbytes,
                    len(self.buffer) - nbytes,
                    cython.address(read),
                )
                if ret == 1:
                    nbytes += read
                    continue

                error = ossl.SSL_get_error(self.ssl, ret)
                if error == ossl.SSL_ERROR_WANT_READ:
                    if self.want_write:
                        self.loop.remove_writer(self.fd)
                        self.loop.add_reader(self.fd, self._read_parse_write)
                        self.want_write = False
                    self.reading = False
                    break
                if error == ossl.SSL_ERROR_WANT_WRITE:
                    if not self.want_write:
                        self.loop.remove_reader(self.fd)
                        self.loop.add_writer(self.fd, self._read_parse_write)
                        self.want_write = True
                    break
                self._handle_error(error)
                return
            self._parse_and_write(nbytes)
        if len(self.pipeline) < self.pipeline_size and self.articles:
            if self.command is None:
                self.pipeline.append(self.articles.pop())
                self.command = b"BODY <" + self.pipeline[-1].encode() + b">\r\n"
            ret = ossl.SSL_write_ex(
                self.ssl,
                cython.cast(cython.pointer[cython.const[cython.char]], self.command),
                len(self.command),
                cython.address(written),
            )
            if ret == 1:
                self.command = None
                if self.want_write:
                    self.loop.remove_writer(self.fd)
                    self.loop.add_reader(self.fd, self._read_parse_write)
                    self.want_write = False
                self.reading = True
                return

            error = ossl.SSL_get_error(self.ssl, ret)
            if error == ossl.SSL_ERROR_WANT_READ:
                if self.want_write:
                    self.loop.remove_writer(self.fd)
                    self.loop.add_reader(self.fd, self._read_parse_write)
                    self.want_write = False
                self.reading = False
            elif error == ossl.SSL_ERROR_WANT_WRITE:
                if not self.want_write:
                    self.loop.remove_reader(self.fd)
                    self.loop.add_writer(self.fd, self._read_parse_write)
                    self.want_write = True
                self.reading = False
            else:
                self._handle_error(error)
        elif not self.articles and not self.pipeline:
            self.loop.remove_reader(self.fd)
            self.loop.remove_writer(self.fd)
            self.result.set_result(None)
        else:
            self.reading = True

    @cython.cfunc
    def _parse_and_write(self, nbytes: cython.size_t):
        write_callback = cast(
            Callable[[memoryview, str, int, int, str], None], self.write_callback
        )
        for article in self.parser.parse(nbytes):
            if article.state == ArticleState.COMPLETE:
                message_id = self.pipeline.popleft()
                write_callback(
                    article.data,
                    article.filename,
                    article.index,
                    article.size,
                    message_id,
                )
            elif article.state == ArticleState.IN_PROGRESS:
                write_callback(
                    article.data,
                    article.filename,
                    article.index,
                    article.size,
                    self.pipeline[0],
                )
                article.index += len(article.data)
            elif article.state in (
                ArticleState.MISSING,
                ArticleState.CRC_FAILED,
                ArticleState.ABORTED,
            ):
                self.pipeline.popleft()

    @cython.cfunc
    def _handle_error(self, error: cython.int) -> None:
        self.loop.remove_reader(self.fd)
        self.loop.remove_writer(self.fd)
        self.articles.extend(self.pipeline)
        self.pipeline.clear()
        if error == ossl.SSL_ERROR_ZERO_RETURN:
            self.result.set_exception(ssl.SSLZeroReturnError())
        elif error == ossl.SSL_ERROR_SYSCALL:
            self.result.set_exception(ssl.SSLSyscallError())
        elif error == ossl.SSL_ERROR_SSL:
            self.result.set_exception(ssl.SSLError())
        else:
            self.result.set_exception(ssl.SSLError())

    def close(self) -> None:
        """Stop watching and close the SSL-owned socket."""
        self.loop.remove_reader(self.fd)
        self.loop.remove_writer(self.fd)
        if self.ssl != cython.NULL:
            ossl.SSL_free(self.ssl)
            self.ssl = cython.NULL

    ############################################################
    # below are the boring functions to establish a connection #
    ############################################################

    @cython.ccall
    def _run_io_operation(self, operation: Callable[[], cython.int]) -> None:
        ret: cython.int
        error: cython.int

        self.loop.remove_reader(self.fd)
        self.loop.remove_writer(self.fd)

        ret = operation()
        if ret == 1:
            self.result.set_result(None)
            return

        error = ossl.SSL_get_error(self.ssl, ret)
        if error == ossl.SSL_ERROR_WANT_READ:
            self.loop.add_reader(self.fd, self._run_io_operation, operation)
        elif error == ossl.SSL_ERROR_WANT_WRITE:
            self.loop.add_writer(self.fd, self._run_io_operation, operation)
        else:
            self._handle_error(error)

    async def tls_handshake(self) -> None:
        self.result = self.loop.create_future()
        self._run_io_operation(lambda: ossl.SSL_connect(self.ssl))
        await self.result

    async def send_bytes(self, data: bytes) -> None:
        written: cython.size_t = 0

        self.result = self.loop.create_future()
        self._run_io_operation(
            lambda: ossl.SSL_write_ex(
                self.ssl,
                cython.cast(cython.pointer[cython.const[cython.char]], data),
                len(data),
                cython.address(written),
            )
        )
        await self.result

    async def read_line(self) -> bytes:
        data: bytearray = bytearray()
        num_read: cython.size_t
        buf: bytearray = bytearray(256)

        while not data.endswith(b"\n"):
            num_read = 0
            self.result = self.loop.create_future()
            self._run_io_operation(
                lambda: ossl.SSL_read_ex(
                    self.ssl,
                    cython.cast(cython.p_char, buf),
                    len(buf),
                    cython.address(num_read),  # noqa: B023
                )
            )
            try:
                await self.result
            except ssl.SSLZeroReturnError as error:
                error.reason = (data + buf[:num_read]).decode("utf-8", errors="replace")
                raise
            data.extend(buf[:num_read])
        return bytes(data)
