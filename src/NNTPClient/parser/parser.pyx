# cython: boundscheck=False, wraparound=False

cimport cython
from cpython.buffer cimport PyBUF_READ
from cpython.memoryview cimport PyMemoryView_FromMemory
from libc.string cimport memchr
import logging
from rapidyenc cimport (
    RapidYencDecoderEnd,
    RapidYencDecoderState,
    rapidyenc_crc,
    rapidyenc_crc_init,
    rapidyenc_decode_incremental,
    rapidyenc_decode_init,
)

cdef object logger = logging.getLogger(__name__)

cdef enum ParserState:
    INITIAL_RESP
    YBEGIN
    YPART
    BODY
    YEND

@cython.final
cdef class Parser:
    """Incrementally parses NNTP traffic with pipelined BODY commands.

    Parser.parse() returns a tuple of Article objects in the order the
    articles were parsed.  An article object is returned only when
    an article has failed and/or there are decoded bytes to be handled.
    The bytearray it is constructed with will be filled upstream with
    raw NNTP traffic.  Upon calling parse, the buffer will be written
    in place with decoded binary data.

    The parser has the following states for each portion of the NNTP
    traffic: initial response, ybegin, ypart, body, yend.  Each state
    has its own private method parse_<state>.  Each can be resumed
    after a partial read of a line (see `read_line()`).
    """
    cdef ParserState state
    cdef unsigned char[::1] buf
    cdef bytes partial_line
    cdef void* write_ptr # initialized to buf
    # -- state regarding the current article -- #
    cdef list articles
    cdef Py_ssize_t article_index
    cdef Py_ssize_t initial_article_index
    cdef bint include_current_article
    cdef Py_ssize_t circ_article_buf_size
    cdef Article current_article
    cdef size_t size
    cdef unsigned int crc32
    cdef RapidYencDecoderState decoder_state

    def __init__(self, bytearray buf, Py_ssize_t pipeline_size):
        self.buf = buf
        self.partial_line = None
        self.circ_article_buf_size = pipeline_size + 1
        self.articles = [Article() for _ in range(self.circ_article_buf_size)]
        self.article_index = 0
        self.current_article = self.articles[self.article_index]
        rapidyenc_decode_init()
        rapidyenc_crc_init()


    cpdef tuple parse(self, Py_ssize_t nbytes):
        cdef const unsigned char[::1] data = self.buf[:nbytes]
        cdef Py_ssize_t i, article_count
        cdef list parsed_articles

        self.initial_article_index = self.article_index
        self.include_current_article = False
        self.write_ptr = &self.buf[0]
        if self.state == ParserState.BODY:
            self.parse_body(data)
        elif self.state == ParserState.INITIAL_RESP:
            self.parse_initial_response(data)
        elif self.state == ParserState.YBEGIN:
            self.parse_ybegin(data)
        elif self.state == ParserState.YPART:
            self.parse_ypart(data)
        elif self.state == ParserState.YEND:
            self.parse_yend(data)

        article_count = (self.article_index - self.initial_article_index) % self.circ_article_buf_size
        if self.include_current_article:
            article_count += 1
        parsed_articles = [None] * article_count
        for i in range(article_count):
            parsed_articles[i] = self.articles[
                (self.initial_article_index + i) % self.circ_article_buf_size
            ]
        return tuple(parsed_articles)

    cdef void parse_initial_response(self, const unsigned char[::1] data) noexcept:
        cdef bytes line
        cdef Py_ssize_t bytes_read

        self.state = ParserState.INITIAL_RESP
        line = self.read_line(data, &bytes_read)
        if bytes_read == 0:
            return

        if line == b'.\r\n':
            self.parse_initial_response(data[bytes_read:])
            return
        if line.startswith((b'220', b'222')):
            self.current_article.state = ArticleState.IN_PROGRESS
            # Suspicious; analyze later.
            self.decoder_state = RapidYencDecoderState.RYDEC_STATE_CRLF
            self.crc32 = 0
            self.parse_ybegin(data[bytes_read:])
            return
        self.current_article.state = ArticleState.MISSING
        self.parse_next_article(data[bytes_read:])

    cdef void parse_next_article(self, const unsigned char[::1] data) noexcept:
        self.article_index = (self.article_index + 1) % self.circ_article_buf_size
        self.current_article = self.articles[self.article_index]
        self.include_current_article = False
        self.parse_initial_response(data)

    cdef void parse_ybegin(self, const unsigned char[::1] data) noexcept:
        cdef bytes line, size
        cdef Py_ssize_t bytes_read

        self.state = ParserState.YBEGIN
        line = self.read_line(data, &bytes_read)
        if bytes_read == 0:
            return
        self.current_article.filename = line.partition(b'name=')[2].rstrip(b'\r\n').decode(
            'utf-8', errors='replace'
        )
        if line.find(b'part=') != -1:
            self.parse_ypart(data[bytes_read:])
            return
        size = line.partition(b'size=')[2].split(maxsplit=1)[0]
        self.size = int(size) if size.isdigit() else 0 # add try except here?
        self.current_article.size = self.size
        self.current_article.beginning = self.current_article.index = 0
        self.parse_body(data[bytes_read:])

    cdef void parse_ypart(self, const unsigned char[::1] data) noexcept:
        cdef bytes line
        cdef Py_ssize_t begin, end
        cdef Py_ssize_t bytes_read

        self.state = ParserState.YPART
        line = self.read_line(data, &bytes_read)
        if bytes_read == 0:
            return
        try:
            begin = int(line.partition(b'begin=')[2].split(maxsplit=1)[0])
            end = int(line.partition(b'end=')[2].split(maxsplit=1)[0])
            self.size = end - begin + 1
            if self.size <= 0:
                raise Exception
        except Exception as e:
            logger.error("Malformed ypart line detected: " + line.decode())
            self.current_article.state = ArticleState.ABORTED
            # TODO: return self.skip_article()
        self.current_article.size = self.size
        self.current_article.beginning = self.current_article.index = begin - 1
        self.parse_body(data[bytes_read:])

    cdef void parse_body(self, const unsigned char[::1] data) noexcept:
        cdef const void* read_ptr
        cdef unsigned char* write_start
        cdef size_t decoded
        cdef RapidYencDecoderEnd decoder_end

        self.state = ParserState.BODY
        if data.shape[0] == 0:
            return

        read_ptr = &data[0]
        write_start = <unsigned char*>self.write_ptr
        decoder_end = rapidyenc_decode_incremental(
            &read_ptr,
            &self.write_ptr,
            data.shape[0],
            &self.decoder_state,
        )

        decoded = <unsigned char*>self.write_ptr - write_start
        self.size -= decoded
        self.crc32 = rapidyenc_crc(write_start, decoded, self.crc32)
        self.include_current_article = True
        self.current_article.data = PyMemoryView_FromMemory(
            <char*>write_start, decoded, PyBUF_READ
        )
        self.current_article.state = ArticleState.IN_PROGRESS
        # If self.size < 0, more bytes were produced than expected. Handle this edge case later.
        if decoder_end != RapidYencDecoderEnd.RYDEC_END_CONTROL:  # End of buffer reached.
            return
        self.parse_yend(data[<const unsigned char*>read_ptr - &data[0]:])

    cdef void parse_yend(self, const unsigned char[::1] data) noexcept:
        cdef bytes line, crc32
        cdef Py_ssize_t bytes_read

        self.state = ParserState.YEND
        line = self.read_line(data, &bytes_read)
        if bytes_read == 0:
            return
        crc32 = line.partition(b'pcrc32=')[2]
        if not crc32:
            crc32 = line.partition(b'crc32=')[2]
        crc32 = crc32.split(maxsplit=1)[0]
        if int(crc32, 16) != self.crc32:
            self.current_article.state = ArticleState.CRC_FAILED
        else:
            self.current_article.state = ArticleState.COMPLETE
        self.parse_next_article(data[bytes_read:])

        # As of now there's no guarding against malformed input. we're assuming everything is nice.
        # In the future we might want to try something else

    cdef bytes read_line(self, const unsigned char[::1] data, Py_ssize_t* bytes_read) noexcept:
        cdef unsigned char* newline
        cdef Py_ssize_t line_length
        cdef bytes line

        if data.shape[0] == 0:
            bytes_read[0] = 0
            return None

        newline = <unsigned char*>memchr(&data[0], b'\n'[0], data.shape[0])
        if newline == NULL:
            bytes_read[0] = 0
            line = bytes(data)
            if self.partial_line is None:
                self.partial_line = line
            else:
                self.partial_line += line
            return None

        line_length = newline - &data[0] + 1
        bytes_read[0] = line_length
        line = bytes(data[:line_length])
        if self.partial_line is not None:
            line = self.partial_line + line
            self.partial_line = None
        return line

cpdef enum ArticleState:
    IN_PROGRESS
    MISSING
    COMPLETE
    CRC_FAILED
    UNKNOWN
    ABORTED

cdef class Article:
    cdef public str filename
    cdef public Py_ssize_t size
    cdef public Py_ssize_t beginning
    cdef public Py_ssize_t index
    cdef public memoryview data
    cdef public ArticleState state
