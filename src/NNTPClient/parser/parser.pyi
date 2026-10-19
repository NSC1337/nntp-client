from enum import IntEnum


class ArticleState(IntEnum):
    IN_PROGRESS: ArticleState
    MISSING: ArticleState
    COMPLETE: ArticleState
    CRC_FAILED: ArticleState
    UNKNOWN: ArticleState
    ABORTED: ArticleState


class Article:
    filename: str
    size: int
    beginning: int
    index: int
    data: memoryview
    state: ArticleState


class Parser:
    def __init__(self, buf: bytearray, pipeline_size: int) -> None: ...
    def parse(self, nbytes: int) -> tuple[Article, ...]: ...
