# nntp client
This is a lightweight and fast native command-line NNTP client written entirely in Python/Cython with no threads.  I made this because sabnzbd and nzbget provide more functionality than I need and have too much configuration.  This program just takes in an NZB and outputs your Linux ISOs.  On my hardware (Thinkpad T490 i7-8665U), it can sustain 12 Gbit/s download and decode (while writing to `/dev/null`).

## Install and run
Requires Linux.
```sh
uv sync
uv run nntp example.nzb
```

## How it works

For brief context, NNTP is the text-based protocol of Usenet, which is only used for sharing binaries nowadays.  On Usenet, binaries are broken up into thousands of individual posts (about 1 MB) containing metadata and binary data encoded as text using yEncode.  It is the client's job to accept a list of article IDs, request them from the news server, decode the yEncode data, assemble the files, repair them if necessary (using PAR2), and then extract the files if applicable (7z or RAR).

News servers can serve files incredibly fast (over multiple connections).  A reasonable upper bound for power users is 10 Gbits/s.  I aimed to create a Python-based client that can sustain 10 Gbit/s in a single Python process on modest hardware.

The first hurdle was downloading 10 Gbits/s with TLS enabled and having extra slack for decoding the traffic.  I had two options: asyncio.BufferedProtocol or managing the connections myself with `loop.add_reader/writer` and direct OpenSSL calls.  I wrote a few small benchmarks to test each approach. The code can be seen in [`benchmarks/download`](benchmarks/download).

| Implementation                  | Wall throughput (Gbit/s) |
|---------------------------------|-------------------------:|
| BufferedProtocol                | 3.594                    |
| BufferedProtocol + uvloop        | 14.988                   |
| Cython + OpenSSL                 | 17.464                   |
| Cython + OpenSSL + uvloop        | 17.121                   |

Cython + OpenSSL was the consistent winner, so I chose it for my implementation, which can be found in [`src/NNTPClient/connection.py`](src/NNTPClient/connection.py).

The second hurdle was parsing the yEncoded messages, which is deceptively challenging.  NNTP traffic can be pipelined, which means you can send multiple requests for articles without waiting for the first article to be delivered.  That means the parser must handle reading multiple articles, partial articles, missing articles, and corrupted articles, all the while being resumable at the subsequent call.  I ended up using Cython for the parser (seen in [`src/NNTPClient/parser/`](src/NNTPClient/parser/)) and vendoring rapidyenc, a SIMD yEncode library from animetosho.  Benchmarks show it can read about 32 Gbits/s.

## Acknowledgments

This project uses [rapidyenc](https://github.com/animetosho/rapidyenc) by
**animetosho and contributors**, whose yEnc implementation is public domain
(or CC0 where public domain is not recognized). Thank you to its authors for
making this high-performance library available. Bundled third-party code retains
its own license terms, including the separately licensed CRC implementations;
see [third-party acknowledgments](THIRD_PARTY_NOTICES.md) for details.
