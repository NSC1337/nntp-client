import hashlib
import os
import tempfile
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import BinaryIO


class FileType(Enum):
    RAR5 = auto()
    RAR_LEGACY = auto()
    SEVEN_Z = auto()
    OTHER = auto()


@dataclass(frozen=True)
class FileInfo:
    filename: str
    file_type: FileType
    md5_16k: bytes


MAX_OPEN_FILES = 16

files: OrderedDict[str, BinaryIO] = OrderedDict()
article_files: dict[str, FileInfo] = {}
_cached_articles: dict[str, tuple[int, bytearray]] = {}

download_dir: Path


@contextmanager
def writer_context() -> Iterator[None]:
    global download_dir

    cache_dir = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    cache_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=cache_dir) as temp_dir:
        download_dir = Path(temp_dir)
        try:
            yield
        finally:
            for file in files.values():
                file.close()
            files.clear()
            article_files.clear()
            _cached_articles.clear()
            del download_dir


def write_to_disk(
    data: memoryview | bytearray,
    filename: str,
    offset: int,
    article_size: int = 0,
    message_id: str = "",
) -> None:
    f = files.get(filename)
    if f is None:
        path = download_dir / filename
        f = open(path, "r+b" if path.exists() else "xb", buffering=0)  # noqa: SIM115
        files[filename] = f
        if len(files) > MAX_OPEN_FILES:
            _, evicted = files.popitem(last=False)
            evicted.close()
    else:
        files.move_to_end(filename)

    f.seek(offset)
    f.write(data)


def recon_write_to_disk(
    data: memoryview | bytearray,
    filename: str,
    offset: int,
    article_size: int,
    message_id: str,
) -> None:
    cached = _cached_articles.get(message_id)
    if cached is None:
        cached = _cached_articles[message_id] = (offset, bytearray(article_size))
    beginning, article = cached
    start = offset - beginning
    end = start + len(data)
    article[start:end] = data
    if end != len(article):
        return

    if article.startswith(b"Rar!\x1a\x07\x01\x00"):
        file_type = FileType.RAR5
    elif article.startswith(b"Rar!\x1a\x07\x00"):
        file_type = FileType.RAR_LEGACY
    elif article.startswith(b"7z\xbc\xaf\x27\x1c"):
        file_type = FileType.SEVEN_Z
    else:
        file_type = FileType.OTHER

    article_files[message_id] = FileInfo(
        filename=filename,
        file_type=file_type,
        md5_16k=hashlib.md5(article[: 16 * 1024]).digest(),
    )
    write_to_disk(article, filename, beginning)
    del _cached_articles[message_id]

