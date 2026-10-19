from NNTPClient.openssl cimport *

cdef extern from "openssl/ssl.h":
    int SSL_CTX_load_verify_locations(SSL_CTX* ctx, const char* file, const char* directory)
    void SSL_CTX_free(SSL_CTX* ctx)
