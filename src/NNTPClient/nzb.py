import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


@dataclass
class NZBFile:
    subject: str
    segments: list[str]


@dataclass
class NZB:
    password: str
    files: list[NZBFile]
    size: int


def read_nzb(path: Path) -> NZB:
    """Accepts a path to an existing well formed .nzb."""
    ns = {"nzb": "http://www.newzbin.com/DTD/2003/nzb"}
    root = ET.parse(path).getroot()
    password = root.findtext(
        "./nzb:head/nzb:meta[@type='password']",
        default="",
        namespaces=ns,
    )

    files: list[NZBFile] = []
    size = 0
    for file_element in root.findall("nzb:file", ns):
        segments: list[str] = []
        for segment_element in sorted(
            file_element.findall("./nzb:segments/nzb:segment", ns),
            key=lambda segment: int(segment.attrib["number"]),
        ):
            segments.append(segment_element.text)
            size += int(segment_element.attrib["bytes"])

        files.append(NZBFile(subject=file_element.attrib["subject"], segments=segments))

    return NZB(password=password, files=files, size=size)
