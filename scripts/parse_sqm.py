#!/usr/bin/env python3
"""
SQM Mission File Parser for Arma 3

Parses Arma 3 .sqm mission files (Arma's "Rapified" binary config format)
and extracts mission metadata and all placed entities (objects, vehicles, units).

The SQM format consists of typed entries:
  Type 0x00 = Class (contains nested entries, prefixed with size dword)
  Type 0x01 = Value (ASCIIZ string or 4-byte int/float)
  Type 0x02 = Array (count dword + elements)

Usage: python parse_sqm.py <input.sqm> <output_directory>
"""

import sys
import os
import json
import struct
from pathlib import Path


class SqmBinaryParser:
    """
    Parser for Arma 3's Rapified config binary format (.sqm files).

    Entry types:
      0x00 = Class  (nested container)
      0x01 = Value  (property value)
      0x02 = Array  (indexed items)

    Value types are determined by context - strings are ASCIIZ,
    numbers are 4-byte little-endian integers or floats.
    """

    def __init__(self, filepath: str):
        self.filepath = filepath
        with open(filepath, "rb") as f:
            self.data = f.read()
        self.pos = 0

    def parse(self) -> dict:
        """Parse and return structured data."""
        self._skip_header()
        root = self._read_class_body(until_end=True)

        mission_data = self._extract_mission(root)
        return {"raw": root, "mission": mission_data}

    def _skip_header(self):
        """Skip the Rapified config header."""
        # Magic: \x00raP (4 bytes)
        magic = b"\x00raP"
        idx = self.data.find(magic)
        if idx >= 0:
            self.pos = idx + 4
        else:
            self.pos = 0
            return

        # Skip 4 bytes (always 0 for SQM) + 4 bytes (enum table offset, always 8)
        self.pos += 8

        # Find content after enum table
        # Look for QO marker
        qo = self.data.find(b"QO", self.pos)
        if qo >= 0:
            self.pos = qo + 2
            # Skip a few bytes after QO (typically 00 00 00 XX)
            while self.pos < len(self.data) and self.data[self.pos] in (0x00, 0x08, 0x09, 0x0A):
                self.pos += 1
                if self.pos >= len(self.data):
                    break

    def _read_byte(self) -> int:
        if self.pos >= len(self.data):
            raise EOFError()
        b = self.data[self.pos]
        self.pos += 1
        return b

    def _read_int32(self) -> int:
        raw = self.data[self.pos : self.pos + 4]
        self.pos += 4
        return struct.unpack("<i", raw)[0]

    def _read_uint32(self) -> int:
        raw = self.data[self.pos : self.pos + 4]
        self.pos += 4
        return struct.unpack("<I", raw)[0]

    def _read_float(self) -> float:
        raw = self.data[self.pos : self.pos + 4]
        self.pos += 4
        return struct.unpack("<f", raw)[0]

    def _read_asciiz(self) -> str:
        end = self.data.find(b"\x00", self.pos)
        if end == -1:
            s = self.data[self.pos :].decode("ascii", errors="replace")
            self.pos = len(self.data)
            return s
        s = self.data[self.pos : end].decode("ascii", errors="replace")
        self.pos = end + 1
        return s

    def _read_variable_int(self) -> int:
        """Read a variable-length encoded integer (used in some SQM files)."""
        result = 0
        shift = 0
        while True:
            if self.pos >= len(self.data):
                break
            b = self._read_byte()
            result |= (b & 0x7F) << shift
            if (b & 0x80) == 0:
                break
            shift += 7
        return result

    def _read_value(self) -> object:
        """
        Read a property value.
        The format after a value entry (type 0x01 + name ASCIIZ) is:
        - If the next byte looks like printable ASCII, it's a string (ASCIIZ)
        - Otherwise it's a 4-byte numeric value (int or float)
        """
        if self.pos >= len(self.data):
            return None

        # Check what's coming next
        remaining = len(self.data) - self.pos

        if remaining < 1:
            return None

        b0 = self.data[self.pos]

        # If the next byte is 0x01 (value prefix in some encodings), skip it
        if b0 == 0x01:
            self.pos += 1
            if self.pos >= len(self.data):
                return None
            b0 = self.data[self.pos]

        # Check if it looks like a string (printable ASCII range)
        if 0x20 <= b0 <= 0x7E:
            # String value - read ASCIIZ
            s = self._read_asciiz()
            # Validate it's reasonable
            if s and len(s) > 0 and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_./\\- " for c in s):
                return s
            # Might still be a valid string
            return s

        # Try 4-byte numeric
        if remaining >= 4:
            # Try as float first
            raw = self.data[self.pos : self.pos + 4]
            try:
                fval = struct.unpack("<f", raw)[0]
                # Check if it's a clean float (not NaN, reasonable range)
                if fval == fval and abs(fval) < 1e30:
                    self.pos += 4
                    return fval
            except Exception:
                pass

            # Try as int
            ival = struct.unpack("<i", raw)[0]
            self.pos += 4
            return ival

        # Try 1-byte value
        return self._read_byte()

    def _read_class_body(self, until_end: bool = False) -> dict:
        """
        Read entries within a class body.
        Each entry is: type_byte + name_asciiz + value/body
        """
        result = {}

        while self.pos < len(self.data):
            if self.pos >= len(self.data):
                break

            entry_type = self.data[self.pos]
            self.pos += 1

            if entry_type == 0xFF or entry_type > 0x02 and entry_type < 0x10:
                # Might be end marker or padding
                if entry_type == 0x00:
                    # Could be start of a class or end marker
                    # Check if followed by null terminator
                    if self.pos < len(self.data) and self.data[self.pos] == 0x00:
                        self.pos += 1
                        break
                    # It's a sub-class
                    name = self._read_asciiz()
                    if not name:
                        break
                    result[name] = self._read_class_body()
                elif entry_type == 0x01:
                    name = self._read_asciiz()
                    if not name:
                        continue
                    value = self._read_value()
                    result[name] = value
                elif entry_type == 0x02:
                    name = self._read_asciiz()
                    if not name:
                        continue
                    result[name] = self._read_array_body()
                else:
                    # Unknown - try to skip
                    if until_end:
                        break
            elif entry_type == 0x00:
                name = self._read_asciiz()
                if not name:
                    break
                result[name] = self._read_class_body()
            elif entry_type == 0x01:
                name = self._read_asciiz()
                if not name:
                    continue
                result[name] = self._read_value()
            elif entry_type == 0x02:
                name = self._read_asciiz()
                if not name:
                    continue
                result[name] = self._read_array_body()
            else:
                # Unknown byte, try to re-sync
                pass

        return result

    def _read_array_body(self) -> list:
        """Read array elements."""
        items = []
        # Arrays are typically preceded by a count
        # In SQM the first bytes might be the count

        saved = self.pos
        try:
            count = self._read_uint32()
            if count > 100000:
                self.pos = saved
        except Exception:
            self.pos = saved

        while self.pos < len(self.data):
            if self.pos >= len(self.data):
                break

            entry_type = self.data[self.pos]
            self.pos += 1

            if entry_type == 0x00:
                name = self._read_asciiz()
                if not name:
                    break
                items.append({name: self._read_class_body()})
            elif entry_type == 0x01:
                name = self._read_asciiz()
                if not name:
                    items.append(self._read_value())
                else:
                    items.append({name: self._read_value()})
            elif entry_type == 0x02:
                name = self._read_asciiz()
                if not name:
                    break
                items.append({name: self._read_array_body()})
            elif entry_type > 0x02:
                # Likely end of array
                self.pos -= 1
                break

        return items

    def _extract_mission(self, root: dict) -> dict:
        """Extract mission data from parsed root dictionary."""
        mission = {
            "name": Path(self.filepath).stem,
            "author": "",
            "addons": [],
            "entities": [],
            "time": {},
            "weather": {},
            "map_name": "",
        }

        # Author
        mission["author"] = root.get("author", "")

        # Addons
        editor = root.get("EditorData", {})
        if isinstance(editor, dict):
            addons_raw = editor.get("addons", [])
            if isinstance(addons_raw, list):
                mission["addons"] = [
                    item if isinstance(item, str) else list(item.values())[0] if isinstance(item, dict) and len(item) > 0 else str(item)
                    for item in addons_raw
                ]

        # Mission data
        scenario = root.get("ScenarioData", {})
        if isinstance(scenario, dict):
            mission_data = scenario.get("Mission", {})
        else:
            mission_data = root.get("Mission", {})

        if isinstance(mission_data, dict):
            # Intel (time & weather)
            intel = mission_data.get("Intel", {})
            if isinstance(intel, dict):
                time_fields = ["year", "month", "day", "hour", "minute"]
                for field in time_fields:
                    v = intel.get(field, 0)
                    if isinstance(v, (int, float)):
                        mission["time"][field] = int(v)
                weather_fields = [
                    "startWeather", "startWind", "startWaves",
                    "forecastWeather", "forecastWind", "forecastWaves",
                    "forecastLightnings"
                ]
                for field in weather_fields:
                    v = intel.get(field, 0)
                    if isinstance(v, (int, float)):
                        mission["weather"][field] = float(v)

            # Entities
            entities_raw = mission_data.get("Entities", [])
            if isinstance(entities_raw, list):
                mission["entities"] = self._parse_entities(entities_raw)

        # Guess map
        mission["map_name"] = self._guess_map(mission.get("addons", []))
        return mission

    def _parse_entities(self, entities_list: list) -> list:
        """Parse entities from raw list."""
        result = []

        for group_item in entities_list:
            if not isinstance(group_item, dict):
                continue

            # Check if this is a Group or standalone Object
            data_type = None
            if "dataType" in group_item:
                data_type = group_item["dataType"]
            else:
                for k, v in group_item.items():
                    if isinstance(v, str) and v in ("Group", "Object", "Logic"):
                        data_type = v
                        break
                    if isinstance(v, dict):
                        dt = v.get("dataType", "")
                        if dt in ("Group", "Object"):
                            data_type = dt
                            break

            if data_type == "Group":
                result.extend(self._parse_group(group_item))
            elif data_type == "Object":
                obj = self._parse_single_object(group_item)
                if obj:
                    result.append(obj)

        return result

    def _parse_group(self, group: dict) -> list:
        """Parse a group and extract all its objects."""
        side = group.get("side", "Unknown")
        gid = group.get("id", 0)
        items = group.get("items", [])

        if isinstance(items, dict):
            # items might be Item0, Item1, ...
            items = [v for k, v in sorted(items.items()) if k.startswith("Item")]

        if not isinstance(items, list):
            return []

        entities = []
        for item in items:
            if isinstance(item, dict):
                obj = self._parse_single_object(item, side, gid)
                if obj:
                    entities.append(obj)

        return entities

    def _parse_single_object(
        self, obj: dict, group_side: str = None, group_id: int = None
    ) -> dict | None:
        """Parse a single object/vehicle/unit entry."""
        # Type/classname
        obj_type = obj.get("type", "")
        if not obj_type:
            attrs = obj.get("Attributes", {})
            if isinstance(attrs, dict):
                obj_type = attrs.get("type", "")

        if not obj_type:
            return None

        # Side
        side = obj.get("side", group_side or "Empty")

        # ID
        obj_id = obj.get("id", 0)
        if isinstance(obj_id, dict):
            obj_id = list(obj_id.values())[0] if obj_id else 0

        # Position - search in multiple locations
        x, y, z = 0, 0, 0
        found_pos = False

        # Check PositionInfo
        pos_info = obj.get("PositionInfo", {})
        if isinstance(pos_info, dict):
            pos = pos_info.get("position", None)
            if isinstance(pos, list) and len(pos) >= 3:
                x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
                found_pos = True

        # Check direct position
        if not found_pos:
            pos = obj.get("position", None)
            if isinstance(pos, list) and len(pos) >= 3:
                x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
                found_pos = True

        if not found_pos:
            return None

        # Angles
        azimuth = 0.0
        if isinstance(pos_info, dict):
            angles = pos_info.get("angles", None)
            if isinstance(angles, list) and len(angles) >= 3:
                azimuth = float(angles[0])
        else:
            angles = obj.get("angles", None)
            if isinstance(angles, list) and len(angles) >= 3:
                azimuth = float(angles[0])

        # Flags
        flags = obj.get("flags", 0)
        if isinstance(flags, dict):
            flags = list(flags.values())[0] if flags else 0

        # Attributes
        attrs = obj.get("Attributes", {})
        is_player = False
        if isinstance(attrs, dict):
            is_player = attrs.get("isPlayer", False)

        entity = {
            "type": str(obj_type),
            "side": str(side),
            "id": int(obj_id) if obj_id is not None else 0,
            "flags": int(flags) if flags is not None else 0,
            "x": x,
            "y": y,
            "z": z,
            "azimuth": azimuth,
            "isPlayer": bool(is_player),
        }

        if group_id is not None:
            entity["groupId"] = int(group_id) if group_id is not None else 0

        return entity

    def _guess_map(self, addons: list) -> str:
        """Try to guess the terrain from addon names."""
        # Precise terrain identifiers — only match standalone terrain names, not generic prefixes
        terrain_indicators = [
            # (pattern in addon name, map name)
            ("Chernarus", "Chernarus"),
            ("chrnarus", "Chernarus"),
            ("Altis", "Altis"),
            ("Stratis", "Stratis"),
            ("Tanoa", "Tanoa"),
            ("Malden", "Malden"),
            ("Livonia", "Livonia"),
            ("Enoch", "Livonia"),
            ("takistan", "Takistan"),
            ("zargabad", "Zargabad"),
            ("utes", "Utes"),
            ("sara", "Sahrani"),
            ("lingor", "Lingor"),
            ("panthera", "Panthera"),
        ]
        for addon in addons:
            a = str(addon)
            # Skip generic CUP core addons that don't indicate a specific terrain
            if a in ("CUP_StandaloneTerrains_Core_Faction", "CUP_StandaloneTerrains_Core"):
                continue
            a_lower = a.lower()
            for pattern, name in terrain_indicators:
                if pattern.lower() in a_lower:
                    return name
        return ""


# ===== FALLBACK: Regex/text-based parser =====

def parse_sqm_regex(filepath: str) -> dict:
    """
    Fallback parser using regex on the raw bytes.
    Extracts entities by finding known byte patterns.
    """
    import re
    from pathlib import Path

    with open(filepath, "rb") as f:
        raw = f.read()

    mission = {
        "name": Path(filepath).stem,
        "author": "",
        "addons": [],
        "entities": [],
        "time": {},
        "weather": {},
        "map_name": "",
    }

    # Decode as Latin-1 (preserves all bytes)
    text = raw.decode("latin-1")

    # Author
    m = re.search(r"author\x00([^\x00]{1,100})", text)
    if m:
        mission["author"] = m.group(1).strip()

    # Addons
    # Find all addon classnames between "addons\x00" and the next section
    m = re.search(r"addons\x00(.*?)(?=Item\d|AddonsMetaData|\x00\x00\x00)", text, re.DOTALL)
    if m:
        addon_section = m.group(1)
        # Extract classnames (look for patterns like: \x00ClassName\x00)
        names = re.findall(r"\x00([A-Za-z0-9_]{3,})\x00", addon_section)
        mission["addons"] = [n for n in names if n not in ("Item", "int", "float", "string")]

    # Time/weather
    m = re.search(r"year\x00([^\x00]{1,4})", text)
    if m:
        try:
            mission["time"]["year"] = int(re.search(r"\d+", m.group(1)).group())
        except Exception:
            pass
    m = re.search(r"month\x00([^\x00]{1,4})", text)
    if m:
        try:
            mission["time"]["month"] = int(re.search(r"\d+", m.group(1)).group())
        except Exception:
            pass
    m = re.search(r"day\x00([^\x00]{1,4})", text)
    if m:
        try:
            mission["time"]["day"] = int(re.search(r"\d+", m.group(1)).group())
        except Exception:
            pass
    m = re.search(r"hour\x00([^\x00]{1,4})", text)
    if m:
        try:
            mission["time"]["hour"] = int(re.search(r"\d+", m.group(1)).group())
        except Exception:
            pass

    # Extract entities
    # Method: find each "type\x00CLASSNAME\x00" and extract position nearby
    entities = []
    pos_search = 0

    while True:
        type_idx = text.find("type\x00", pos_search)
        if type_idx == -1:
            break

        # Get the classname
        type_end = type_idx + 5  # skip "type\x00"
        type_name_end = text.find("\x00", type_end)
        if type_name_end == -1:
            break
        classname = text[type_end:type_name_end].strip()

        # Look for side near this type
        side_search_start = max(0, type_idx - 500)
        side_search_end = type_idx
        side_match = re.search(r"side\x00([^\x00]+)", text[side_search_start:side_search_end])
        side = side_match.group(1).strip() if side_match else "Empty"

        # Look for position near this type
        pos_search_start = max(0, type_idx - 200)
        pos_search_end = min(len(text), type_idx + 500)
        chunk = text[pos_search_start:pos_search_end]

        pos_match = re.search(r"position\x00", chunk)
        if pos_match:
            # Position data: after "position\x00":
            # Byte 0: count (usually 0x03 for 3 coordinates)
            # Then for each coord: 0x01 prefix + 4-byte IEEE 754 float
            raw_start = pos_search_start + pos_match.end()
            if raw_start + 16 <= len(raw):
                try:
                    count = raw[raw_start]
                    if count >= 1 and count <= 4 and raw_start + 1 + count * 5 <= len(raw):
                        floats_read = []
                        off = raw_start + 1  # skip count byte
                        for i in range(count):
                            off += 1  # skip 0x01 prefix
                            fbytes = raw[off : off + 4]
                            off += 4
                            floats_read.append(struct.unpack("<f", fbytes)[0])
                        if len(floats_read) >= 3:
                            x, y, z = floats_read[0], floats_read[1], floats_read[2]
                            if abs(x) < 1000000 and abs(y) < 100000 and abs(z) < 1000000:
                                # Now look for angles\x00 nearby (after position data)
                                azimuth = 0.0
                                angles_search = raw[off:off + 50]
                                angles_match = re.search(rb"angles\x00", angles_search)
                                if angles_match:
                                    angle_start = off + angles_match.end()
                                    if angle_start + 1 + 3 * 5 <= len(raw):
                                        try:
                                            acount = raw[angle_start]
                                            aoff = angle_start + 1
                                            angle_floats = []
                                            for ai in range(min(acount, 3)):
                                                aoff += 1  # skip prefix
                                                abytes = raw[aoff : aoff + 4]
                                                aoff += 4
                                                angle_floats.append(struct.unpack("<f", abytes)[0])
                                            if len(angle_floats) >= 2:
                                                azimuth = angle_floats[1]  # Y rotation is azimuth (radians)
                                        except Exception:
                                            pass
                                
                                entities.append({
                                    "type": classname,
                                    "side": side,
                                    "id": len(entities),
                                    "flags": 0,
                                    "x": x,
                                    "y": y,
                                    "z": z,
                                    "azimuth": azimuth,
                                    "isPlayer": "isPlayer" in chunk,
                                })
                except Exception:
                    pass

        pos_search = type_idx + 1

    mission["entities"] = entities

    # Guess map
    mission["map_name"] = _guess_map_regex(mission.get("addons", []))
    return {"mission": mission}


def _guess_map_regex(addons: list) -> str:
    """Precise terrain guesser that skips generic CUP core addons."""
    terrain_indicators = [
        ("Chernarus", "Chernarus"),
        ("chrnarus", "Chernarus"),
        ("Altis", "Altis"),
        ("Stratis", "Stratis"),
        ("Tanoa", "Tanoa"),
        ("Malden", "Malden"),
        ("Livonia", "Livonia"),
        ("Enoch", "Livonia"),
        ("takistan", "Takistan"),
        ("zargabad", "Zargabad"),
        ("utes", "Utes"),
        ("sara", "Sahrani"),
        ("lingor", "Lingor"),
        ("panthera", "Panthera"),
    ]
    for addon in addons:
        a = str(addon)
        # Skip generic CUP core addons
        if a in ("CUP_StandaloneTerrains_Core_Faction", "CUP_StandaloneTerrains_Core"):
            continue
        a_lower = a.lower()
        for pattern, name in terrain_indicators:
            if pattern.lower() in a_lower:
                return name
    return ""


def main():
    if len(sys.argv) < 3:
        print("Usage: python parse_sqm.py <input.sqm> <output_directory>")
        sys.exit(1)

    sqm_path = sys.argv[1]
    output_dir = sys.argv[2]

    if not os.path.exists(sqm_path):
        print(f"Error: File not found: {sqm_path}")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    # Try regex parser (more reliable for this format)
    try:
        data = parse_sqm_regex(sqm_path)
        parser_used = "regex"
    except Exception as e:
        print(f"Regex parser failed: {e}")
        try:
            parser = SqmBinaryParser(sqm_path)
            data = parser.parse()
            parser_used = "binary"
        except Exception as e2:
            print(f"Binary parser also failed: {e2}")
            sys.exit(1)

    mission = data.get("mission", {})

    # Write meta.json
    meta = {
        "name": mission.get("name", Path(sqm_path).stem),
        "author": mission.get("author", ""),
        "addons": mission.get("addons", []),
        "time": mission.get("time", {}),
        "weather": mission.get("weather", {}),
        "map_name": mission.get("map_name", ""),
        "entity_count": len(mission.get("entities", [])),
    }

    with open(os.path.join(output_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, default=str)

    # Write entities.json
    entities = mission.get("entities", [])
    with open(os.path.join(output_dir, "entities.json"), "w", encoding="utf-8") as f:
        json.dump(entities, f, indent=2, default=str)

    print(f"Parsed {sqm_path} (using {parser_used} parser)")
    print(f"  Entities found: {len(entities)}")
    print(f"  Author: {meta['author']}")
    print(f"  Addons: {len(meta['addons'])}")
    print(f"  Map guess: {meta['map_name']}")
    print(f"  Output: {output_dir}")


if __name__ == "__main__":
    main()