from libc.stddef cimport size_t
from libc.stdint cimport uint32_t


cdef extern from "rapidyenc/rapidyenc.h":
    ctypedef enum RapidYencDecoderState:
        RYDEC_STATE_CRLF
        RYDEC_STATE_EQ
        RYDEC_STATE_CR
        RYDEC_STATE_NONE
        RYDEC_STATE_CRLFDT
        RYDEC_STATE_CRLFDTCR
        RYDEC_STATE_CRLFEQ

    ctypedef enum RapidYencDecoderEnd:
        RYDEC_END_NONE
        RYDEC_END_CONTROL
        RYDEC_END_ARTICLE

    void rapidyenc_decode_init()

    RapidYencDecoderEnd rapidyenc_decode_incremental(
        const void** src,
        void** dest,
        size_t src_length,
        RapidYencDecoderState* state,
    )

    void rapidyenc_crc_init()

    uint32_t rapidyenc_crc(
        const void* src,
        size_t src_length,
        uint32_t init_crc,
    )
