"""How wide and how tall an uploaded picture is, without decoding it.

Meta refuses an image below a few hundred pixels a side, and it refuses it
at ad-creation time - which is to say in front of a customer, after
everything else has already worked. The check is worth doing at upload,
where it costs nothing and is something the person can act on.

No Pillow. Pillow decodes images; this reads the first few dozen bytes of
a header, which is all a width and a height ever needed. That is one fewer
compiled dependency in the runtime image, and for a check this narrow the
library would be carrying a darkroom to read a label.

Unknown is a real answer and is spelled ``None``: a video, a truncated
upload, an exotic encoder. The caller must let those through rather than
refuse what it could not measure.
"""

import struct
from typing import Final

# JPEG's frame headers, the ones that carry the dimensions. C4, C8 and CC
# share the range and are Huffman and arithmetic tables, not frames -
# reading a size out of those is how a "clever" parser returns nonsense.
_JPEG_FRAME_MARKERS: Final = frozenset(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}

# How far into a file the header is looked for. EXIF blocks push a JPEG's
# frame header a long way in; a quarter of a megabyte covers a phone
# photograph with a thumbnail embedded, and past that the answer is that
# we do not know.
MAX_HEADER_BYTES: Final = 256 * 1024


def read_size(data: bytes) -> tuple[int, int] | None:
    """Width and height in pixels, or ``None`` when they cannot be read."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return _png(data)
    if data.startswith(b"\xff\xd8"):
        return _jpeg(data)
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return _webp(data)
    return None


def _png(data: bytes) -> tuple[int, int] | None:
    """IHDR is always the first chunk, at a fixed offset."""
    if len(data) < 24 or data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return _checked(width, height)


def _jpeg(data: bytes) -> tuple[int, int] | None:
    """Walk the segment chain to the frame header.

    Segments carry their own length, so this is a walk rather than a search
    for a byte pattern - a search finds the marker inside embedded EXIF
    thumbnails and reports their size instead.
    """
    index = 2
    end = min(len(data), MAX_HEADER_BYTES)

    while index + 9 < end:
        if data[index] != 0xFF:
            index += 1
            continue

        marker = data[index + 1]
        if marker in _JPEG_FRAME_MARKERS:
            height, width = struct.unpack(">HH", data[index + 5 : index + 9])
            return _checked(width, height)

        # 0xD0-0xD9 are standalone markers with no length field; skipping
        # two bytes past them is the only correct move.
        if 0xD0 <= marker <= 0xD9 or marker == 0xFF:
            index += 2
            continue

        (length,) = struct.unpack(">H", data[index + 2 : index + 4])
        if length < 2:
            return None
        index += 2 + length

    return None


def _webp(data: bytes) -> tuple[int, int] | None:
    """Three encodings under one container, each with its own header."""
    chunk = data[12:16]

    if chunk == b"VP8 " and data[23:26] == b"\x9d\x01\x2a":
        width, height = struct.unpack("<HH", data[26:30])
        return _checked(width & 0x3FFF, height & 0x3FFF)

    if chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
        (bits,) = struct.unpack("<I", data[21:25])
        return _checked((bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1)

    if chunk == b"VP8X" and len(data) >= 30:
        width = int.from_bytes(data[24:27], "little") + 1
        height = int.from_bytes(data[27:30], "little") + 1
        return _checked(width, height)

    return None


def _checked(width: int, height: int) -> tuple[int, int] | None:
    """A zero side is a corrupt header, not a picture nought pixels wide."""
    return (width, height) if width > 0 and height > 0 else None
