"""
render_topdown.py — Render a top-down overview of an Arma 3 map.

Usage:
    python render_topdown.py <map_dir> [output.png] [--width W] [--height H]

    <map_dir>   Path to the parsed map directory (contains terrain_class.png,
                objects.json, roadnet.json, meta.json).
    output.png  Output image path (default: topdown_<mapname>.png).
    --width W      Output pixel width  (default: 4096, or auto from terrain_class.png).
    --height H     Output pixel height (default: 4096, or auto from terrain_class.png).
    --no-terrain   Skip terrain_class.png background and use a solid color.
    --bg-color     Hex background color if --no-terrain is used (default: #0f172a).

Dependencies: Pillow
"""

import json
import os
import sys
import argparse
import math
from PIL import Image, ImageDraw, ImageFont


# ── Colours ─────────────────────────────────────────────────────────────────

CATEGORY_COLOURS = {
    "buildings":  ( 56, 189, 248),   # #38bdf8  sky blue
    "nature":     ( 34, 197,  94),   # #22c55e  green
    "clutter":    (120, 113, 108),   # #78716c  warm gray
    "roads":      ( 51,  65,  85),   # #334155  slate
    "structures": (100, 116, 139),   # #64748b  blue-gray
    "lamps":      (250, 204,  21),   # #facc15  yellow
}

ROAD_COLOURS = {
    "track":    (214, 194, 166),   # #D6C2A6
    "road":     (178, 178, 178),   # #B2B2B2
    "mainRoad": (230, 128,  76),   # #E6804C
}


def load_classification():
    """Load classification.json if present for object categorisation."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    class_path = os.path.join(script_dir, "..", "web", "classification.json")
    if os.path.exists(class_path):
        with open(class_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def classify_object(cls_name: str, classification: dict) -> str:
    """Map an object class name to a category label."""
    cls_lower = cls_name.lower()
    if classification and cls_lower in classification:
        return classification[cls_lower]
    if cls_lower.startswith("t_") or cls_lower.startswith("b_"):
        return "nature"
    if cls_lower.startswith("c_"):
        return "clutter"
    if any(kw in cls_lower for kw in ["tree", "bush"]):
        return "nature"
    if any(kw in cls_lower for kw in ["house", "building", "office", "shop"]):
        return "buildings"
    if any(kw in cls_lower for kw in ["wall", "fence", "hide"]):
        return "structures"
    if any(kw in cls_lower for kw in ["lamp", "light"]):
        return "lamps"
    if any(kw in cls_lower for kw in ["road", "track"]):
        return "roads"
    return "clutter"


def load_meta(map_dir: str):
    """Load meta.json to get map dimensions, cell size, etc."""
    meta_path = os.path.join(map_dir, "meta.json")
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def render_objects(draw, objects_file: str, meta: dict, classification: dict,
                   img_w: int, img_h: int):
    """Stream objects.json and draw each object as a coloured dot."""
    map_size = meta.get("mapSize", 8192)
    file_size = os.path.getsize(objects_file)

    with open(objects_file, "rb") as f:
        # Read header to find the byte position of '[' after "objects"
        accumulated = b''
        array_start = -1
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            accumulated += chunk
            idx = accumulated.find(b'"objects"')
            if idx != -1:
                arr_idx = accumulated.find(b'[', idx)
                if arr_idx != -1:
                    array_start = arr_idx
                    break

        if array_start == -1:
            print("  (could not find objects array in JSON)")
            return

        # Position file just after the '['
        f.seek(array_start + 1)

        # Now stream-parse JSON objects using raw_decode (same approach as server.py)
        decoder = json.JSONDecoder()
        buffer = ''
        count = 0
        bytes_read = array_start + 1

        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            try:
                text = chunk.decode('utf-8')
            except UnicodeDecodeError:
                text = chunk.decode('utf-8', errors='replace')
            buffer += text
            bytes_read += len(chunk)

            while True:
                # Trim leading whitespace and separators
                stripped = buffer.lstrip(' \t\n\r,')
                if not stripped:
                    buffer = ''
                    break
                if stripped[0] == ']':
                    return  # end of objects array — we're done

                try:
                    obj, end = decoder.raw_decode(stripped)
                except json.JSONDecodeError:
                    # Incomplete object — need more data
                    break

                # Consume the parsed object from the buffer
                buffer = stripped[end:]

                x = obj.get("x")
                y = obj.get("y")
                if x is not None and y is not None:
                    # World → image pixel (center)
                    cx = x / map_size * img_w
                    # Arma Y is bottom-up, image Y is top-down
                    cy = (map_size - y) / map_size * img_h

                    if not (-50 <= cx < img_w + 50 and -50 <= cy < img_h + 50):
                        continue

                    cat = classify_object(obj.get("class", ""), classification)
                    colour = CATEGORY_COLOURS.get(cat, CATEGORY_COLOURS["clutter"])

                    # Real-world dimensions in meters, with scale
                    w = (obj.get("w") or 1) * (obj.get("scaleX") or 1)
                    l = (obj.get("l") or 1) * (obj.get("scaleZ") or 1)

                    # Convert to pixels
                    pix_w = w / map_size * img_w
                    pix_l = l / map_size * img_h

                    # Minimum 2×2 pixels for visibility
                    if pix_w < 2.0 and pix_l < 2.0:
                        px, py = int(cx), int(cy)
                        if 0 <= px < img_w and 0 <= py < img_h:
                            draw.point((px, py), fill=colour)
                        continue

                    # Draw rotated rectangle using the object's yaw (dir)
                    # dir=0 = north (up in image). The standard 2D rotation
                    # matrix rotates clockwise in screen coords (Y↓), so
                    # dir=90 → +90° → length axis points right (east). ✅
                    angle_deg = obj.get("dir") or 0
                    angle_rad = math.radians(angle_deg)

                    hw = pix_w / 2.0
                    hl = pix_l / 2.0

                    # Four corners of the rectangle, unrotated
                    corners = [
                        (-hw, -hl),
                        ( hw, -hl),
                        ( hw,  hl),
                        (-hw,  hl),
                    ]

                    # Rotate and translate
                    cos_a = math.cos(angle_rad)
                    sin_a = math.sin(angle_rad)
                    poly = []
                    for dx, dy in corners:
                        rx = dx * cos_a - dy * sin_a + cx
                        ry = dx * sin_a + dy * cos_a + cy
                        poly.append((int(rx), int(ry)))

                    # Outline for larger objects, filled for smaller
                    if max(pix_w, pix_l) > 6:
                        draw.polygon(poly, outline=colour, fill=colour)
                    else:
                        draw.polygon(poly, fill=colour)

                count += 1
                if count % 100000 == 0:
                    pct = 100.0 * bytes_read / file_size if file_size else 0
                    print(f"  Objects: {count:,} parsed ({min(pct, 100):.0f}% of file)...")

        print(f"  Objects: {count:,} total processed.")


def render_roads(draw, roadnet_file: str, meta: dict, img_w: int, img_h: int):
    """Render roads as polylines from roadnet.json."""
    if not os.path.exists(roadnet_file):
        print("  (no roadnet.json — skipping roads)")
        return

    with open(roadnet_file, "r", encoding="utf-8") as f:
        roadnet = json.load(f)

    roads = roadnet.get("roads", [])
    map_size = roadnet.get("mapSize", meta.get("mapSize", 8192))

    if not roads:
        print("  (roadnet.json has no roads)")
        return

    drawn = 0
    for road in roads:
        pts = road.get("pts", [])
        if len(pts) < 2:
            continue

        road_type = road.get("type", "road")
        colour = ROAD_COLOURS.get(road_type, ROAD_COLOURS["road"])
        width_m = road.get("width", 10.0)
        # Scale road width to pixels (rough; two-lane road ~10m, pixel line width minimum 1)
        line_w = max(1, int(width_m / map_size * max(img_w, img_h)))

        # Convert world coords → image pixels
        pixels = []
        for pt in pts:
            px = int(pt[0] / map_size * img_w)
            py = int((map_size - pt[1]) / map_size * img_h)
            pixels.append((px, py))

        # Draw polyline
        if len(pixels) >= 2:
            draw.line(pixels, fill=colour, width=line_w)
            drawn += 1

    print(f"  Roads: {drawn:,} segments drawn.")


def render_names(draw, names_file: str, meta: dict, img_w: int, img_h: int):
    map_size = meta.get("mapSize", 8192)
    with open(names_file, "r", encoding="utf-8") as f:
        names = json.load(f)
        
    try:
        font_city = ImageFont.truetype("arial.ttf", 60)
        font_village = ImageFont.truetype("arial.ttf", 40)
        font_local = ImageFont.truetype("arial.ttf", 30)
    except IOError:
        font_city = font_village = font_local = ImageFont.load_default()
        
    for place in names:
        name = place.get("name", "")
        if not name:
            continue
            
        x = place.get("x", 0)
        y = place.get("y", 0)
        p_type = place.get("type", "")
        
        px = (x / map_size) * img_w
        # y coordinates in Arma are from bottom to top, image is top to bottom
        py = img_h - ((y / map_size) * img_h)
        
        font = font_local
        color = (255, 255, 255)
        if p_type == "NameCityCapital":
            font = font_city
            color = (255, 255, 100)
        elif p_type == "NameCity":
            font = font_city
        elif p_type == "NameVillage":
            font = font_village
            
        # Draw shadow
        draw.text((px+2, py+2), name, fill=(0,0,0), font=font, anchor="ms")
        draw.text((px, py), name, fill=color, font=font, anchor="ms")


def main():
    parser = argparse.ArgumentParser(
        description="Render a top-down map overview with terrain, objects, and roads."
    )
    parser.add_argument("map_dir", help="Path to parsed map directory")
    parser.add_argument("output", nargs="?", help="Output PNG path (default: topdown_<mapname>.png)")
    parser.add_argument("--width", type=int, default=0, help="Output width in pixels")
    parser.add_argument("--height", type=int, default=0, help="Output height in pixels")
    parser.add_argument("--no-objects", action="store_true", help="Skip object rendering")
    parser.add_argument("--no-roads", action="store_true", help="Skip road rendering")
    parser.add_argument("--no-names", action="store_true", help="Skip name rendering")
    parser.add_argument("--no-terrain", action="store_true",
                        help="Skip terrain_class.png background (solid colour instead)")
    parser.add_argument("--bg-color", type=str, default="#0f172a",
                        help="Background colour when --no-terrain is used (hex, default: #0f172a)")
    args = parser.parse_args()

    map_dir = os.path.abspath(args.map_dir)
    if not os.path.isdir(map_dir):
        print(f"Error: {map_dir} is not a directory.")
        sys.exit(1)

    print(f"Map directory: {map_dir}")

    # ── 1. Determine output size ───────────────────────────────────────────
    img_w = args.width or 4096
    img_h = args.height or 4096
    terrain_img = None

    if not args.no_terrain:
        terr_path = os.path.join(map_dir, "terrain_class.png")
        if os.path.exists(terr_path):
            terrain_img = Image.open(terr_path)
            img_w = args.width or terrain_img.width
            img_h = args.height or terrain_img.height
            print(f"Terrain texture: {terrain_img.width}×{terrain_img.height}")
        else:
            print("No terrain_class.png found — using solid background.")
    else:
        print(f"No terrain: using solid background ({args.bg_color}).")

    # Create output canvas
    if terrain_img and (terrain_img.width != img_w or terrain_img.height != img_h):
        terrain_img = terrain_img.resize((img_w, img_h), Image.LANCZOS)

    if terrain_img:
        canvas = terrain_img.copy()
    else:
        # Parse hex background colour
        bg_hex = args.bg_color.lstrip('#')
        bg_rgb = tuple(int(bg_hex[i:i+2], 16) for i in (0, 2, 4))
        canvas = Image.new("RGB", (img_w, img_h), bg_rgb)

    draw = ImageDraw.Draw(canvas)

    # ── 2. Load metadata ──────────────────────────────────────────────────
    meta = load_meta(map_dir)
    if meta:
        print(f"Map size: {meta.get('mapSize', '?')}m")

    # ── 3. Render objects ─────────────────────────────────────────────────
    if not args.no_objects:
        objects_path = os.path.join(map_dir, "objects.json")
        if os.path.exists(objects_path):
            classification = load_classification()
            print(f"Rendering objects from {objects_path} ({os.path.getsize(objects_path):,} bytes)...")
            render_objects(draw, objects_path, meta, classification, img_w, img_h)
        else:
            print(f"  (objects.json not found — skipping objects)")
    else:
        print("  (--no-objects: skipping objects)")

    # ── 4. Render roads ───────────────────────────────────────────────────
    if not args.no_roads:
        roadnet_path = os.path.join(map_dir, "roadnet.json")
        if os.path.exists(roadnet_path):
            print(f"Rendering roads from {roadnet_path}...")
            render_roads(draw, roadnet_path, meta, img_w, img_h)
        else:
            print(f"  (roadnet.json not found — skipping roads)")
    else:
        print("  (--no-roads: skipping roads)")

    # ── 4.5. Render names ──────────────────────────────────────────────────
    if not args.no_names:
        names_path = os.path.join(map_dir, "names.json")
        if os.path.exists(names_path):
            print(f"Rendering place names from {names_path}...")
            render_names(draw, names_path, meta, img_w, img_h)
    else:
        print("  (--no-names: skipping place names)")

    # ── 5. Save output ────────────────────────────────────────────────────
    map_name = os.path.basename(map_dir.rstrip("/\\"))
    output_path = args.output or os.path.join(map_dir, f"topdown_{map_name}.png")
    canvas.save(output_path, "PNG")
    file_size_kb = os.path.getsize(output_path) / 1024
    print(f"\nSaved {output_path}  ({img_w}×{img_h}, {file_size_kb:.0f} KB)")


if __name__ == "__main__":
    main()