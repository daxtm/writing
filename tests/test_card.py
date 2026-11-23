"""Tests for card PNG decoding: pure card_png_json and the thin file wrapper."""

import base64
import json
import struct
import zlib

import longform


def chunk(ctype, body):
    return struct.pack(">I", len(body)) + ctype + body + struct.pack(">I", zlib.crc32(ctype + body))


def png(*chunks):
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunks)


def card(name="Mara"):
    return {"name": name, "description": "a harbour thief"}


def b64(d):
    return base64.b64encode(json.dumps(d).encode("utf-8"))


def text_chunk(key, value):
    k = key.encode("latin-1") if isinstance(key, str) else key
    return chunk(b"tEXt", k + b"\x00" + value)


def itxt(key, value, compressed=False):
    k = key.encode("latin-1") if isinstance(key, str) else key
    rest = bytes([1 if compressed else 0, 0]) + b"\x00" + b"\x00" + (
        zlib.compress(value) if compressed else value)
    return chunk(b"iTXt", k + b"\x00" + rest)


def decode(data):
    return longform.card_png_json(data)


def test_non_png_returns_none():
    assert decode(b"not a png at all") is None
    assert decode(b"") is None


def test_text_chara_chunk():
    d = decode(png(text_chunk(b"chara", b64(card()))))
    assert d == card()


def test_ccv3_preferred_over_chara():
    d = decode(png(text_chunk(b"chara", b64(card("Old"))), itxt(b"ccv3", b64(card("V3")))))
    assert d["name"] == "V3"


def test_chara_used_when_no_ccv3():
    d = decode(png(text_chunk(b"chara", b64(card()))))
    assert d["name"] == "Mara"


def test_itxt_compressed_and_uncompressed():
    d = decode(png(itxt(b"ccv3", b64(card("Plain")))))
    assert d["name"] == "Plain"
    d = decode(png(itxt(b"ccv3", b64(card("Zipped")), compressed=True)))
    assert d["name"] == "Zipped"


def test_other_chunks_and_iend_ignored():
    data = png(chunk(b"IHDR", b"1234"), text_chunk(b"chara", b64(card())), chunk(b"IEND", b""),
               text_chunk(b"chara", b"ignored-after-iend"))
    assert decode(data)["name"] == "Mara"


def test_malformed_payload_returns_none():
    assert decode(png(text_chunk(b"chara", b"not base64 %%%"))) is None
    assert decode(png(text_chunk(b"chara", base64.b64encode(b"not json")))) is None
    assert decode(png(itxt(b"ccv3", b64(card()), compressed=True)[:-4])) is None


def test_bad_itxt_compression_skipped_not_fatal():
    body = b"ccv3\x00" + bytes([1, 0]) + b"\x00\x00" + b"\x00\x00\x00garbage"
    data = png(chunk(b"iTXt", body), text_chunk(b"chara", b64(card())))
    assert decode(data)["name"] == "Mara"


def test_truncated_chunk_stream_stops_cleanly():
    assert decode(png(text_chunk(b"chara", b64(card())))[:-10])["name"] == "Mara"


def test_wrapper_reads_file(tmp_path):
    path = tmp_path / "card.png"
    path.write_bytes(png(text_chunk(b"chara", b64(card()))))
    assert longform.read_card_png(path) == card()
    (tmp_path / "plain.txt").write_bytes(b"hello")
    assert longform.read_card_png(tmp_path / "plain.txt") is None
