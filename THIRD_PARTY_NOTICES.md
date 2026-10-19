# Third-party acknowledgments

Bundled third-party code retains its own licensing and attribution notices.

## rapidyenc

This project vendors [rapidyenc](https://github.com/animetosho/rapidyenc),
by **animetosho and contributors**, in `src/NNTPClient/parser/rapidyenc/`.
Thank you to its authors for the SIMD yEnc encoder/decoder and CRC routines
used by this client.

As stated in rapidyenc's README, the module is dedicated to the **public
domain**, or [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/legalcode)
(or equivalent) where public domain is not recognized. See the bundled
rapidyenc README for the upstream licensing statement.

rapidyenc also includes code with separate notices and terms:

- **crcutil**: Apache License 2.0; see
  `src/NNTPClient/parser/rapidyenc/crcutil-1.0/LICENSE` and its source headers.
- **CRC folding code derived from zlib-ng / Intel's zlib patch**: zlib license.
  `src/NNTPClient/parser/rapidyenc/src/crc_folding.cc` credits Intel Corporation
  (copyright 2013), Wajdi Feghali, Jim Guilford, Vinodh Gopal, Erdinc Ozturk,
  and Jim Kukunas. The upstream license is linked from rapidyenc's README:
  https://github.com/Dead2/zlib-ng/blob/develop/LICENSE.md.
- **Hedley** (`src/hedley.h` within rapidyenc): public domain / CC0 1.0,
  as stated in its header.
- **stdint compatibility header** (`src/stdint.h` within rapidyenc):
  copyright 2006–2008 Alexander Chemeris; its redistribution conditions and
  disclaimer are preserved in that header.

Original upstream notices in the vendored sources are retained.
