import asyncio
import shutil
from pathlib import Path

from NNTPClient import writer


async def repair_and_extract() -> None:
    download_dir = writer.download_dir
    output_dir = Path.cwd()

    par2_file = next(
        (path for path in download_dir.iterdir() if path.suffix.lower() == ".par2"),
        None,
    )
    if par2_file:
        process = await asyncio.create_subprocess_exec(
            "par2", "repair", par2_file.name, cwd=download_dir
        )
        await process.wait()

    rar_files = sorted(path for path in download_dir.iterdir() if path.suffix.lower() == ".rar")
    rar_file = next((path for path in rar_files if ".part01.rar" in path.name.lower()), None)
    if rar_file is None and rar_files:
        rar_file = rar_files[0]

    if rar_file:
        process = await asyncio.create_subprocess_exec(
            "unrar", "x", "-o+", rar_file.name, str(output_dir), cwd=download_dir
        )
        await process.wait()
    else:
        for path in download_dir.iterdir():
            if path.suffix.lower() != ".par2":
                shutil.move(path, output_dir / path.name)
