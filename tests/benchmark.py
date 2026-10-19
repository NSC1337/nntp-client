import random
import time
import zlib

from NNTPClient.parser import Parser


TARGET_TRAFFIC_BYTES = 100 * 1024 * 1024
ARTICLE_PAYLOAD_BYTES = 32 * 1024
READ_BUFFER_BYTES = 256 * 1024
MIN_READ_BYTES = 100 * 1024
MAX_READ_BYTES = 150 * 1024
RANDOM_SEED = 0x4E4E5450


def _yenc_article(payload: bytes, article_number: int) -> bytes:
    # A zero byte encodes to "*", which needs no yEnc escaping and cannot be
    # mistaken for a control line. This keeps data generation simple and valid.
    encoded = bytes((byte + 42) % 256 for byte in payload)
    crc32 = zlib.crc32(payload)
    return (
        f"222 0 <benchmark-{article_number}@example.com>\r\n"
        f"=ybegin line=128 size={len(payload)} name={article_number}.bin\r\n"
    ).encode() + encoded + (
        f"\r\n=yend size={len(payload)} crc32={crc32:08x}\r\n"
    ).encode()


def _synthetic_traffic(target_size: int) -> tuple[bytes, int]:
    payload = bytes(ARTICLE_PAYLOAD_BYTES)
    articles = []
    total_size = 0

    while total_size < target_size:
        article = _yenc_article(payload, len(articles))
        articles.append(article)
        total_size += len(article)

    return b"".join(articles), len(articles)


def _read_sizes(total_size: int) -> list[int]:
    rng = random.Random(RANDOM_SEED)
    sizes = []
    remaining = total_size

    while remaining:
        size = min(rng.randint(MIN_READ_BYTES, MAX_READ_BYTES), remaining)
        sizes.append(size)
        remaining -= size

    return sizes


def test_parser_benchmark() -> None:
    traffic, article_count = _synthetic_traffic(TARGET_TRAFFIC_BYTES)
    read_sizes = _read_sizes(len(traffic))
    read_buffer = bytearray(READ_BUFFER_BYTES)
    parser = Parser(read_buffer, pipeline_size=article_count + 1)

    offset = 0
    start_ns = time.perf_counter_ns()
    for read_size in read_sizes:
        read_buffer[:read_size] = traffic[offset:offset + read_size]
        parser.parse(read_size)
        offset += read_size
    elapsed_ns = time.perf_counter_ns() - start_ns

    assert offset == len(traffic)

    elapsed_seconds = elapsed_ns / 1_000_000_000
    throughput_mib_s = len(traffic) / elapsed_seconds / (1024 * 1024)
    print(
        f"\nParsed {len(traffic) / (1024 * 1024):.2f} MiB "
        f"in {elapsed_seconds * 1_000:.3f} ms "
        f"({throughput_mib_s:.2f} MiB/s, {len(read_sizes)} reads)"
    )
