from libc.stddef cimport size_t

cdef extern from "openssl/bio.h":
    ctypedef struct BIO:
        pass

    BIO* BIO_new_socket(int sock, int close_flag)

    enum:
        BIO_CLOSE


cdef extern from "openssl/ssl.h":
    ctypedef struct SSL_CTX:
        pass

    ctypedef struct SSL:
        pass

    ctypedef struct SSL_METHOD:
        pass

    ctypedef struct X509_STORE_CTX:
        pass

    ctypedef int (*SSL_verify_cb)(int preverify_ok, X509_STORE_CTX* store)

    const SSL_METHOD* TLS_client_method()
    SSL_CTX* SSL_CTX_new(const SSL_METHOD* method)
    int SSL_CTX_set_default_verify_paths(SSL_CTX* ctx)
    unsigned long SSL_CTX_set_options(SSL_CTX* ctx, unsigned long options)
    void SSL_CTX_set_verify(SSL_CTX* ctx, int mode, SSL_verify_cb callback)

    SSL* SSL_new(SSL_CTX* ctx)
    void SSL_free(SSL* ssl)
    void SSL_set_bio(SSL* ssl, BIO* read_bio, BIO* write_bio)
    long SSL_set_tlsext_host_name(SSL* ssl, const char* hostname)
    int SSL_set1_host(SSL* ssl, const char* hostname)

    int SSL_connect(SSL* ssl)
    int SSL_write_ex(SSL* ssl, const void* buffer, size_t length, size_t* written)
    int SSL_read_ex(SSL* ssl, void* buffer, size_t length, size_t* read)
    int SSL_get_error(const SSL* ssl, int result)

    enum:
        SSL_VERIFY_PEER
        SSL_OP_ENABLE_KTLS
        SSL_ERROR_WANT_READ
        SSL_ERROR_WANT_WRITE
        SSL_ERROR_ZERO_RETURN
        SSL_ERROR_SYSCALL
        SSL_ERROR_SSL
