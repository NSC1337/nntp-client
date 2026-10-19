import argparse
import re
import tomllib
from pathlib import Path

import uvloop

from NNTPClient import config
from NNTPClient.nzb import read_nzb
from NNTPClient.pool import NNTPSession
from NNTPClient.repair_and_extract import repair_and_extract
from NNTPClient.writer import (
    article_files,
    recon_write_to_disk,
    write_to_disk,
    writer_context,
)


async def download(nzb_path: Path) -> None:
    nzb = read_nzb(nzb_path)
    with writer_context():
        async with NNTPSession(config.server.get("connections", 8)) as session:
            first_articles = [file.segments[0] for file in nzb.files if file.segments]
            await session.download(first_articles, recon_write_to_disk)

            def file_order(nzb_file):
                info = article_files.get(nzb_file.segments[0]) if nzb_file.segments else None
                if info is None:
                    return 5, natural_filename_key(nzb_file.subject)
                return file_priority(info.filename), natural_filename_key(info.filename)

            ordered_files = sorted(nzb.files, key=file_order)
            articles = [segment for file in ordered_files for segment in file.segments[1:]]
            # Connections pop articles from the end of the shared list.
            articles.reverse()
            await session.download(articles, write_to_disk)

        await repair_and_extract()


def file_priority(filename: str) -> int:
    filename = filename.lower()
    if filename.endswith(".par2"):
        return 3
    if filename.endswith(".rar") or re.search(r"\.r\d{2,3}$", filename):
        return 1
    if filename.endswith(".7z") or re.search(r"\.7z\.\d{3,}$", filename):
        return 2
    return 4


def natural_filename_key(filename):
    return tuple(
        (part.isdigit(), int(part) if part.isdigit() else part)
        for part in re.split(r"(\d+)", filename.lower())
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("nzb_path", type=Path)
    args = parser.parse_args()
    with open("config.toml", "rb") as file:
        config.server = tomllib.load(file)["server"]
    uvloop.run(download(args.nzb_path))


if __name__ == "__main__":
    main()
