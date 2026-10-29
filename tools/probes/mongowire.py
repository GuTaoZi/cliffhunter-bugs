#!/usr/bin/env python3
"""A minimal MongoDB client for the probe harness: BSON and OP_MSG over a socket, no driver needed.

    c = Mongo(port); c.cmd({"buildInfo": 1})            -> the reply document (dict); raises on ok: 0
    c.cmd({"insert": "t", "documents": [...]}, db="w")

BSON types covered: double, string, document, array, binary, ObjectId, bool, datetime, null, int32, timestamp,
int64 (encoded: dict, list, str, bool, int, float, None, bytes; decoded: also ObjectId, datetime and timestamp as
tagged tuples, decimal128 as raw bytes). Dicts keep their order, as commands need. Int64(n) forces an int64 (a
transaction's txnNumber) and UUIDBin(b) a binary of subtype 4 (a session id: {"id": UUIDBin(uuid.uuid4().bytes)}).
"""
import socket
import struct

OP_MSG = 2013


class Error(Exception):
    pass


class Int64(int):
    """An int encoded as BSON int64 whatever its size."""


class UUIDBin(bytes):
    """Bytes encoded as BSON binary subtype 4 (UUID)."""


def enc_doc(d):
    body = b"".join(enc_elem(str(k), v) for k, v in (d.items() if isinstance(d, dict) else enumerate(d)))
    return struct.pack("<i", len(body) + 5) + body + b"\x00"


def enc_elem(k, v):
    name = k.encode() + b"\x00"
    if isinstance(v, bool):
        return b"\x08" + name + (b"\x01" if v else b"\x00")
    if isinstance(v, Int64):
        return b"\x12" + name + struct.pack("<q", v)
    if isinstance(v, int):
        if -2**31 <= v < 2**31:
            return b"\x10" + name + struct.pack("<i", v)
        return b"\x12" + name + struct.pack("<q", v)
    if isinstance(v, float):
        return b"\x01" + name + struct.pack("<d", v)
    if isinstance(v, str):
        s = v.encode()
        return b"\x02" + name + struct.pack("<i", len(s) + 1) + s + b"\x00"
    if isinstance(v, dict):
        return b"\x03" + name + enc_doc(v)
    if isinstance(v, (list, tuple)):
        return b"\x04" + name + enc_doc(list(v))
    if v is None:
        return b"\x0a" + name
    if isinstance(v, UUIDBin):
        return b"\x05" + name + struct.pack("<i", len(v)) + b"\x04" + v
    if isinstance(v, bytes):
        return b"\x05" + name + struct.pack("<i", len(v)) + b"\x00" + v
    raise TypeError(f"cannot encode {type(v).__name__}")


def dec_doc(b, i=0, array=False):
    n = struct.unpack_from("<i", b, i)[0]
    end, i, out = i + n - 1, i + 4, {}
    while i < end:
        t = b[i]
        j = b.index(b"\x00", i + 1)
        k = b[i + 1:j].decode()
        i = j + 1
        if t == 0x01:
            v = struct.unpack_from("<d", b, i)[0]; i += 8
        elif t in (0x02, 0x0D, 0x0E):
            ln = struct.unpack_from("<i", b, i)[0]; v = b[i + 4:i + 3 + ln].decode(errors="replace"); i += 4 + ln
        elif t in (0x03, 0x04):
            ln = struct.unpack_from("<i", b, i)[0]; v = dec_doc(b, i, t == 0x04); i += ln
        elif t == 0x05:
            ln = struct.unpack_from("<i", b, i)[0]; v = bytes(b[i + 5:i + 5 + ln]); i += 5 + ln
        elif t == 0x07:
            v = ("oid", b[i:i + 12].hex()); i += 12
        elif t == 0x08:
            v = b[i] == 1; i += 1
        elif t == 0x09:
            v = ("date", struct.unpack_from("<q", b, i)[0]); i += 8
        elif t in (0x0A, 0x06, 0x7F, 0xFF):
            v = None
        elif t == 0x0B:
            j = b.index(b"\x00", i); j2 = b.index(b"\x00", j + 1); v = ("regex", b[i:j].decode()); i = j2 + 1
        elif t == 0x10:
            v = struct.unpack_from("<i", b, i)[0]; i += 4
        elif t == 0x11:
            inc, sec = struct.unpack_from("<II", b, i); v = ("ts", sec, inc); i += 8
        elif t == 0x12:
            v = struct.unpack_from("<q", b, i)[0]; i += 8
        elif t == 0x13:
            v = bytes(b[i:i + 16]); i += 16
        else:
            raise Error(f"BSON type {t:#x} not supported")
        out[k] = v
    return list(out.values()) if array else out


class Mongo:
    def __init__(self, port, host="127.0.0.1", timeout=60):
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.rid = 0

    def _recv(self, n):
        buf = bytearray()
        while len(buf) < n:
            chunk = self.s.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return bytes(buf)

    def cmd(self, doc, db="admin", check=True):
        doc = dict(doc)
        doc["$db"] = db
        self.rid += 1
        body = struct.pack("<I", 0) + b"\x00" + enc_doc(doc)
        self.s.sendall(struct.pack("<iiii", 16 + len(body), self.rid, 0, OP_MSG) + body)
        ln, _, _, op = struct.unpack("<iiii", self._recv(16))
        msg = self._recv(ln - 16)
        if op != OP_MSG:
            raise Error(f"reply opcode {op}")
        reply = dec_doc(msg, 5)
        if check and not reply.get("ok"):
            raise Error(f"{reply.get('codeName', '')}: {reply.get('errmsg', reply)}")
        return reply

    def close(self):
        self.s.close()
