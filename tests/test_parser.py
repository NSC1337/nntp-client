import zlib

from NNTPClient.parser import ArticleState, Parser


def yenc_article(payload: bytes, *, beginning: int | None = None) -> bytes:
    encoded = bytes((byte + 42) % 256 for byte in payload)
    crc32 = zlib.crc32(payload)

    if beginning is None:
        header = f"=ybegin line=128 size={len(payload)} name=test.bin\r\n".encode()
        footer = f"=yend size={len(payload)} crc32={crc32:08x}\r\n".encode()
    else:
        end = beginning + len(payload) - 1
        header = (
            f"=ybegin part=1 line=128 size={end} name=test.bin\r\n"
            f"=ypart begin={beginning} end={end}\r\n"
        ).encode()
        footer = (
            f"=yend size={len(payload)} part=1 pcrc32={crc32:08x}\r\n"
        ).encode()

    return b"222 0 <test@example.com>\r\n" + header + encoded + b"\r\n" + footer


def test_parses_a_complete_article():
    payload = b"hello, yEnc!"
    response = yenc_article(payload)
    buf = bytearray(response)
    parser = Parser(buf, pipeline_size=2)

    (article,) = parser.parse(len(response))

    assert article.state == ArticleState.COMPLETE
    assert article.filename == "test.bin"
    assert article.beginning == 0
    assert article.size == len(payload)
    assert buf[:len(payload)] == payload


def test_parses_a_normal_multipart_article():
    payload = b"part two"
    response = yenc_article(payload, beginning=9)
    buf = bytearray(response)
    parser = Parser(buf, pipeline_size=2)

    (article,) = parser.parse(len(response))

    assert article.state == ArticleState.COMPLETE
    assert article.beginning == 8
    assert article.size == len(payload)
    assert buf[:len(payload)] == payload


def test_returns_all_articles_started_during_parse_in_order():
    first_payload = b"first"
    second_payload = b"second"
    response = yenc_article(first_payload) + yenc_article(second_payload)
    buf = bytearray(response)
    parser = Parser(buf, pipeline_size=3)

    first_article, second_article = parser.parse(len(response))
    assert first_article.state == ArticleState.COMPLETE
    assert first_article.size == len(first_payload)
    assert second_article.state == ArticleState.COMPLETE
    assert second_article.size == len(second_payload)
    assert buf[:len(first_payload) + len(second_payload)] == (
        first_payload + second_payload
    )


def test_parses_lines_split_across_reads():
    payload = b"incremental payload"
    response = yenc_article(payload, beginning=9)
    buf = bytearray(len(response))
    parser = Parser(buf, pipeline_size=2)

    for offset in range(0, len(response), 7):
        chunk = response[offset:offset + 7]
        buf[:len(chunk)] = chunk
        article = parser.parse(len(chunk))
    article = article[0]
    assert article.state == ArticleState.COMPLETE
    assert article.beginning == 8
    assert article.size == len(payload)
