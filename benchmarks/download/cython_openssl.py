import asyncio
import os
import socket
from contextlib import asynccontextmanager

import cython
import cython.cimports.openssl_api as ossl


@cython.cfunc
def create_tls(fd: cython.int, certificate: bytes) -> cython.pointer(ossl.SSL):
    ctx = ossl.SSL_CTX_new(ossl.TLS_client_method())
    if ctx == cython.NULL:
        raise MemoryError("SSL_CTX_new failed")
    try:
        if ossl.SSL_CTX_load_verify_locations(ctx, certificate, cython.NULL) != 1:
            raise OSError("Cannot load benchmark certificate")
        ossl.SSL_CTX_set_verify(ctx, ossl.SSL_VERIFY_PEER, cython.NULL)
        tls = ossl.SSL_new(ctx)
    finally:
        ossl.SSL_CTX_free(ctx)
    if tls == cython.NULL:
        raise MemoryError("SSL_new failed")
    try:
        bio = ossl.BIO_new_socket(fd, 0)  # The connection context owns the socket.
        if bio == cython.NULL:
            raise MemoryError("BIO_new_socket failed")
        ossl.SSL_set_bio(tls, bio, bio)
        if ossl.SSL_set1_host(tls, b"localhost") != 1:
            raise OSError("Cannot set TLS verification hostname")
        return tls
    except BaseException:
        ossl.SSL_free(tls)
        raise


@cython.cclass
class Receiver:
    ssl: cython.pointer(ossl.SSL)
    fd: cython.int
    loop: object

    closed = cython.declare(object, visibility="public")
    received = cython.declare(cython.ulonglong, visibility="public")
    buffer: cython.uchar[::1]

    watching: cython.int

    def __init__(self, fd, certificate):
        self.fd, self.loop = fd, asyncio.get_running_loop()
        self.closed = self.loop.create_future()
        self.buffer = bytearray(1024 * 1024)
        self.ssl = create_tls(fd, certificate)

    def read(self):
        count: cython.size_t = 0
        while True:
            ret = ossl.SSL_read_ex(
                self.ssl,
                cython.address(self.buffer[0]),
                len(self.buffer),
                cython.address(count),
            )
            if ret != 1:
                error = ossl.SSL_get_error(self.ssl, ret)
                if error == ossl.SSL_ERROR_WANT_READ:
                    if self.watching != error:
                        self.loop.remove_writer(self.fd)
                        self.loop.add_reader(self.fd, self.read)
                        self.watching = error
                elif error == ossl.SSL_ERROR_WANT_WRITE:
                    if self.watching != error:
                        self.loop.remove_reader(self.fd)
                        self.loop.add_writer(self.fd, self.read)
                        self.watching = error
                else:
                    self.loop.remove_reader(self.fd)
                    self.loop.remove_writer(self.fd)
                    self.watching = 0
                    self.closed.set_result(OSError(f"OpenSSL error {error}"))
                return
            self.received += count

    def close(self):
        self.loop.remove_reader(self.fd)
        self.loop.remove_writer(self.fd)

        ossl.SSL_free(self.ssl)

    async def tls_handshake(self):
        while True:
            ret = ossl.SSL_connect(self.ssl)
            if ret == 1:
                return
            error = ossl.SSL_get_error(self.ssl, ret)
            result = self.loop.create_future()
            if error == ossl.SSL_ERROR_WANT_READ:
                self.loop.add_reader(self.fd, result.set_result, None)
            elif error == ossl.SSL_ERROR_WANT_WRITE:
                self.loop.add_writer(self.fd, result.set_result, None)
            else:
                raise OSError(f"OpenSSL handshake error {error}")
            try:
                await result
            finally:
                self.loop.remove_reader(self.fd)
                self.loop.remove_writer(self.fd)


@asynccontextmanager
async def connect(port, certificate):
    with socket.socket() as sock:
        sock.setblocking(False)
        await asyncio.get_running_loop().sock_connect(sock, ("127.0.0.1", port))
        receiver = Receiver(sock.fileno(), os.fsencode(certificate))
        try:
            await receiver.tls_handshake()
            receiver.read()
            yield receiver
        finally:
            receiver.close()
