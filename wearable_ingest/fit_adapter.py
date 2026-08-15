"""Minimal, local FIT decoder which exposes only approved activity aggregates.

It intentionally does not retain FIT record streams, coordinates, second-level
heart-rate samples, device information, or account identifiers.
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any


class FitDecodeError(ValueError):
    pass


_FIT_EPOCH_UNIX = 631065600
_SIZES = {0x00: 1, 0x01: 1, 0x02: 1, 0x83: 2, 0x84: 2, 0x85: 4, 0x86: 4, 0x88: 4, 0x89: 8, 0x0A: 1, 0x8B: 2, 0x8C: 4, 0x0D: 1}
_SESSION_TOTAL_ELAPSED_TIME_SCALE = 1000.0
_UINT16_INVALID = 0xFFFF
_UINT32_INVALID = 0xFFFFFFFF


def _value(raw: bytes, base_type: int, little_endian: bool) -> int | float:
    if base_type not in _SIZES or len(raw) != _SIZES[base_type]:
        raise FitDecodeError("unsupported_or_malformed_fit_field")
    prefix = "<" if little_endian else ">"
    formats = {0x00: "B", 0x01: "b", 0x02: "B", 0x83: "h", 0x84: "H", 0x85: "i", 0x86: "I", 0x88: "f", 0x89: "d", 0x0A: "B", 0x8B: "H", 0x8C: "I", 0x0D: "B"}
    return struct.unpack(prefix + formats[base_type], raw)[0]


def parse_garmin_fit(path: Path) -> dict[str, Any]:
    """Parse a FIT activity into approved aggregate values, or fail closed."""
    data = path.read_bytes()
    if len(data) < 14 or data[0] < 12 or data[8:12] != b".FIT":
        raise FitDecodeError("invalid_fit_header")
    header_size = data[0]
    if header_size > len(data) or header_size < 12:
        raise FitDecodeError("invalid_fit_header_size")
    data_size = struct.unpack("<I", data[4:8])[0]
    end = header_size + data_size
    if end > len(data):
        raise FitDecodeError("truncated_fit_data")
    definitions: dict[int, tuple[int, list[tuple[int, int, int]], bool]] = {}
    sessions: list[dict[int, int | float]] = []
    record_has_gps = False
    record_has_hr = False
    last_timestamp: int | None = None
    cursor = header_size
    while cursor < end:
        header = data[cursor]
        cursor += 1
        if header & 0x80:
            # Compressed timestamp records have a two-bit local message number
            # and a five-bit timestamp offset.  FIT omits field 253 from the
            # payload; reconstruct it only from an already observed timestamp.
            local = (header >> 5) & 0x03
            compressed_timestamp_offset = header & 0x1F
            if last_timestamp is None:
                raise FitDecodeError("compressed_timestamp_without_prior_timestamp")
            compressed = True
        else:
            local = header & 0x0F
            compressed_timestamp_offset = None
            compressed = False
        if header & 0x40:
            if compressed:
                raise FitDecodeError("invalid_compressed_timestamp_definition")
            if cursor + 5 > end:
                raise FitDecodeError("truncated_fit_definition")
            _reserved, architecture = data[cursor], data[cursor + 1]
            little = architecture == 0
            order = "<" if little else ">"
            global_no = struct.unpack(order + "H", data[cursor + 2:cursor + 4])[0]
            count = data[cursor + 4]
            cursor += 5
            if cursor + count * 3 > end:
                raise FitDecodeError("truncated_fit_field_definition")
            fields = [(data[cursor + index * 3], data[cursor + index * 3 + 1], data[cursor + index * 3 + 2]) for index in range(count)]
            cursor += count * 3
            definitions[local] = (global_no, fields, little)
            continue
        if local not in definitions:
            raise FitDecodeError("data_record_without_definition")
        global_no, fields, little = definitions[local]
        timestamp_fields = [field for field in fields if field[0] == 253]
        if compressed:
            if len(timestamp_fields) != 1 or timestamp_fields[0][1:] != (4, 0x86):
                raise FitDecodeError("compressed_timestamp_without_standard_timestamp_field")
            size = sum(field_size for field_num, field_size, _ in fields if field_num != 253)
            timestamp = (last_timestamp & ~0x1F) + compressed_timestamp_offset
            if timestamp < last_timestamp:
                timestamp += 0x20
        else:
            size = sum(field_size for _, field_size, _ in fields)
            timestamp = None
        if cursor + size > end:
            raise FitDecodeError("truncated_compressed_timestamp_data_record" if compressed else "truncated_fit_data_record")
        values: dict[int, int | float] = {}
        for field_num, field_size, base_type in fields:
            if compressed and field_num == 253:
                values[field_num] = timestamp
                continue
            raw = data[cursor:cursor + field_size]
            cursor += field_size
            expected = _SIZES.get(base_type)
            if expected == field_size:
                values[field_num] = _value(raw, base_type, little)
        if 253 in values:
            field_timestamp = values[253]
            if not isinstance(field_timestamp, (int, float)) or field_timestamp < 0:
                raise FitDecodeError("invalid_fit_timestamp")
            last_timestamp = int(field_timestamp)
        if global_no == 18:
            sessions.append(values)
        elif global_no == 20:
            record_has_gps = record_has_gps or (0 in values and 1 in values)
            record_has_hr = record_has_hr or (3 in values)
    if not sessions:
        raise FitDecodeError("missing_session_message")
    session = sessions[-1]
    required = {2: "start_time", 7: "total_elapsed_time", 9: "total_distance"}
    missing = [name for key, name in required.items() if key not in session]
    if missing:
        raise FitDecodeError("missing_required_session_fields:" + ",".join(missing))
    start = int(session[2]) + _FIT_EPOCH_UNIX
    elapsed_raw = session[7]
    if not isinstance(elapsed_raw, (int, float)) or elapsed_raw == _UINT32_INVALID:
        raise FitDecodeError("invalid_session_total_elapsed_time")
    # FIT profile: session.total_elapsed_time (field 7) is uint32 with a
    # scale of 1000.  Garmin encodes milliseconds, not seconds.
    elapsed = float(elapsed_raw) / _SESSION_TOTAL_ELAPSED_TIME_SCALE
    distance_m = float(session[9]) / 100.0
    if elapsed <= 0 or distance_m < 0:
        raise FitDecodeError("invalid_session_totals")
    avg_hr = session.get(16)
    ascent_raw = session.get(21)
    # FIT's uint16 invalid sentinel must remain missing; exposing 65535 as
    # ascent would contaminate training-load aggregates.
    ascent_m = None if ascent_raw in (None, _UINT16_INVALID) else round(float(ascent_raw), 1)
    return {
        "started_at_unix": start,
        "duration_seconds": round(elapsed, 3),
        "distance_km": round(distance_m / 1000.0, 3),
        "ascent_m": ascent_m,
        "gps_present": record_has_gps,
        "heart_rate_present": bool(record_has_hr or (isinstance(avg_hr, (int, float)) and avg_hr > 0)),
        "average_heart_rate_bpm": round(float(avg_hr), 1) if isinstance(avg_hr, (int, float)) and avg_hr > 0 else None,
    }
