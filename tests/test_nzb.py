from pathlib import Path

from NNTPClient.nzb import NZB, NZBFile, read_nzb

NZB_CONTENT = """<?xml version="1.0" encoding="iso-8859-1" ?>
<!DOCTYPE nzb PUBLIC "-//newzBin//DTD NZB 1.1//EN" "http://www.newzbin.com/DTD/nzb/nzb-1.1.dtd">
<nzb xmlns="http://www.newzbin.com/DTD/2003/nzb">
    <head>
        <meta type="title">Your File!</meta>
        <meta type="password">secret</meta>
        <meta type="tag">HD</meta>
        <meta type="category">TV</meta>
    </head>
    <file poster="Joe Bloggs &lt;bloggs@nowhere.example&gt;" date="1071674882" subject="Here's your file!  abc-mr2a.r01 (1/2)">
        <groups>
            <group>alt.binaries.newzbin</group>
            <group>alt.binaries.mojo</group>
        </groups>
        <segments>
            <segment bytes="102394" number="1">123456789abcdef@news.newzbin.com</segment>
            <segment bytes="4501" number="2">987654321fedbca@news.newzbin.com</segment>
        </segments>
    </file>
</nzb>
"""


def write_nzb(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "test.nzb"
    path.write_text(content, encoding="iso-8859-1")
    return path


def test_read_nzb(tmp_path: Path) -> None:
    nzb = read_nzb(write_nzb(tmp_path, NZB_CONTENT))

    assert nzb == NZB(
        password="secret",
        files=[
            NZBFile(
                subject="Here's your file!  abc-mr2a.r01 (1/2)",
                segments=[
                    "123456789abcdef@news.newzbin.com",
                    "987654321fedbca@news.newzbin.com",
                ],
            )
        ],
        size=106895,
    )


def test_read_nzb_without_password(tmp_path: Path) -> None:
    content = NZB_CONTENT.replace('        <meta type="password">secret</meta>\n', "")

    nzb = read_nzb(write_nzb(tmp_path, content))

    assert nzb.password == ""
