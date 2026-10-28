"""Check a PE32+ DLL export table without a platform-specific inspection tool."""
from pathlib import Path
import struct
import sys


def exports(path):
    data = path.read_bytes()
    u16 = lambda offset: struct.unpack_from("<H", data, offset)[0]
    u32 = lambda offset: struct.unpack_from("<I", data, offset)[0]
    pe = u32(0x3C)
    assert data[pe:pe + 4] == b"PE\0\0", "missing PE signature"
    optional = pe + 24
    assert u16(optional) == 0x20B, "expected PE32+"
    sections = optional + u16(pe + 20)

    def offset(rva):
        for index in range(u16(pe + 6)):
            section = sections + index * 40
            start = u32(section + 12)
            size = max(u32(section + 8), u32(section + 16))
            if start <= rva < start + size:
                return u32(section + 20) + rva - start
        raise AssertionError("RVA outside PE sections")

    directory = offset(u32(optional + 112))
    names = offset(u32(directory + 32))
    result = []
    for index in range(u32(directory + 24)):
        start = offset(u32(names + index * 4))
        result.append(data[start:data.index(b"\0", start)].decode("ascii"))
    return result


if __name__ == "__main__":
    found = exports(Path(sys.argv[1]))
    assert found == ["encore_plugin_entry_v1"], found
