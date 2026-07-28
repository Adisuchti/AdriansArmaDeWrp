import struct
import os
import sys
import json
from PIL import Image

# ── Terrain classification colours ─────────────────────────────────────────
# Based on Geography flags (forest/road/water) + GrassApprox density

# Terrain types and their RGB colours
TERRAIN_DEEP_WATER  = ( 20,  60, 180)   # deep ocean / large water bodies
TERRAIN_SHALLOW     = ( 50, 120, 220)   # shallow water / rivers
TERRAIN_SHORE        = (220, 210, 160)   # beaches / shorelines
TERRAIN_FOREST       = ( 30, 100,  30)   # dense forest
TERRAIN_GRASS        = ( 80, 170,  50)   # grassland / open fields
TERRAIN_DRY_GRASS    = (180, 190,  60)   # dry grass / steppe
TERRAIN_BARE         = (170, 150, 120)   # bare ground / rocky
TERRAIN_ROAD         = ( 80,  80,  80)   # roads
TERRAIN_URBAN        = (180, 160, 150)   # urban / built-up (where objects exist)
TERRAIN_CONCRETE     = (140, 140, 150)   # concrete / runways (very low grass, no forest)


# ── Existing converters (kept for backward compatibility) ───────────────────

def convert_heightmap(base_dir, width, height):
    bin_path = os.path.join(base_dir, "raw", "heightmap.bin")
    if not os.path.exists(bin_path):
        return

    png_path = os.path.join(base_dir, "parsed", "heightmap.png")

    with open(bin_path, "rb") as f:
        floats = struct.unpack(f"<{width*height}f", f.read())

    img = Image.new('RGB', (width, height))
    pixels = img.load()

    min_h = min(floats)
    max_h = max(floats)

    idx = 0
    for y in range(height):
        for x in range(width):
            val = floats[idx]
            norm = (val - min_h) / (max_h - min_h) if max_h > min_h else 0
            rgb_val = int(norm * 16777215)
            r = (rgb_val >> 16) & 255
            g = (rgb_val >> 8) & 255
            b = rgb_val & 255
            pixels[x, y] = (r, g, b)
            idx += 1

    img = img.transpose(Image.FLIP_TOP_BOTTOM)
    img.save(png_path)
    print(f"Saved {png_path}")


def convert_heightmap_grayscale(base_dir, width, height):
    bin_path = os.path.join(base_dir, "raw", "heightmap.bin")
    if not os.path.exists(bin_path):
        return

    png_path = os.path.join(base_dir, "parsed", "heightmap_grey.png")

    with open(bin_path, "rb") as f:
        floats = struct.unpack(f"<{width*height}f", f.read())

    min_h = min(floats)
    max_h = max(floats)
    span = max_h - min_h if max_h > min_h else 1.0

    pixels = bytearray(width * height)
    for i, val in enumerate(floats):
        norm = (val - min_h) / span
        pixels[i] = int(norm * 255)

    img = Image.frombytes('L', (width, height), bytes(pixels))
    img = img.transpose(Image.FLIP_TOP_BOTTOM)
    img.save(png_path)
    print(f"Saved {png_path}")


def convert_material_mask(base_dir, width, height):
    bin_path = os.path.join(base_dir, "raw", "material_mask.bin")
    if not os.path.exists(bin_path):
        return

    png_path = os.path.join(base_dir, "parsed", "material_mask.png")

    with open(bin_path, "rb") as f:
        ushorts = struct.unpack(f"<{width*height}H", f.read())

    # Find unique materials to create a distinct color palette
    unique_mats = list(set(ushorts))
    colors = {}
    import random
    random.seed(42)  # Deterministic colours

    for mat in unique_mats:
        colors[mat] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))

    img = Image.new('RGB', (width, height))
    pixels = img.load()

    idx = 0
    for y in range(height):
        for x in range(width):
            pixels[x, y] = colors[ushorts[idx]]
            idx += 1

    img = img.transpose(Image.FLIP_TOP_BOTTOM)
    img.save(png_path)
    print(f"Saved {png_path}")


def convert_byte_palette(base_dir, filename, width, height, out_name):
    bin_path = os.path.join(base_dir, "raw", filename)
    if not os.path.exists(bin_path):
        return

    png_path = os.path.join(base_dir, "parsed", out_name)
    with open(bin_path, "rb") as f:
        bytes_data = struct.unpack(f"<{width*height}B", f.read()[:width*height])

    unique_vals = list(set(bytes_data))
    colors = {}
    import random
    random.seed(123)
    for v in unique_vals:
        colors[v] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))

    img = Image.new('RGB', (width, height))
    pixels = img.load()
    idx = 0
    for y in range(height):
        for x in range(width):
            pixels[x, y] = colors[bytes_data[idx]]
            idx += 1

    img = img.transpose(Image.FLIP_TOP_BOTTOM)
    img.save(png_path)
    print(f"Saved {png_path}")


def convert_byte_grayscale(base_dir, filename, width, height, out_name):
    bin_path = os.path.join(base_dir, "raw", filename)
    if not os.path.exists(bin_path):
        return

    png_path = os.path.join(base_dir, "parsed", out_name)
    with open(bin_path, "rb") as f:
        bytes_data = struct.unpack(f"<{width*height}B", f.read()[:width*height])

    img = Image.new('L', (width, height))
    pixels = img.load()
    idx = 0
    for y in range(height):
        for x in range(width):
            pixels[x, y] = bytes_data[idx]
            idx += 1

    img = img.transpose(Image.FLIP_TOP_BOTTOM)
    img.save(png_path)
    print(f"Saved {png_path}")


# ── NEW: Meaningful terrain-class PNG from Geography + GrassApprox ──────────

LEGEND_ITEMS = [
    (TERRAIN_DEEP_WATER,  "deep water"),
    (TERRAIN_SHALLOW,     "shallow water"),
    (TERRAIN_SHORE,       "shore / beach"),
    (TERRAIN_FOREST,      "forest"),
    (TERRAIN_GRASS,       "grassland"),
    (TERRAIN_DRY_GRASS,   "dry grass"),
    (TERRAIN_BARE,        "bare / rocky"),
    (TERRAIN_ROAD,        "road"),
    (TERRAIN_CONCRETE,    "concrete / runway"),
    (TERRAIN_URBAN,       "urban / buildings"),
]


def classify_terrain(geography_flags, grass_val):
    """Return (r, g, b, label) for a cell given its Geography bitfield and grass byte (0-255)."""
    # --- Water ---
    min_depth = geography_flags & 0b11
    max_depth = (geography_flags >> 5) & 0b11

    if max_depth >= 2:
        return TERRAIN_DEEP_WATER[0], TERRAIN_DEEP_WATER[1], TERRAIN_DEEP_WATER[2], "deep_water"
    if max_depth >= 1 or min_depth >= 1:
        return TERRAIN_SHALLOW[0], TERRAIN_SHALLOW[1], TERRAIN_SHALLOW[2], "shallow_water"

    # --- Road ---
    is_road = ((geography_flags >> 4) & 0b1) > 0
    if is_road:
        return TERRAIN_ROAD[0], TERRAIN_ROAD[1], TERRAIN_ROAD[2], "road"

    # --- Forest ---
    is_forest = ((geography_flags >> 3) & 0b1) > 0
    if is_forest:
        return TERRAIN_FOREST[0], TERRAIN_FOREST[1], TERRAIN_FOREST[2], "forest"

    # --- Grass / bare by vegetation density ---
    if grass_val >= 150:
        return TERRAIN_GRASS[0], TERRAIN_GRASS[1], TERRAIN_GRASS[2], "grassland"
    if grass_val >= 60:
        return TERRAIN_DRY_GRASS[0], TERRAIN_DRY_GRASS[1], TERRAIN_DRY_GRASS[2], "dry_grass"

    # Very low grass — likely concrete, bare, or shore
    # Heuristic: if it's near water (but not flagged as water), call it shore
    # Otherwise classify by elevation context below
    return TERRAIN_BARE[0], TERRAIN_BARE[1], TERRAIN_BARE[2], "bare_ground"


def convert_primary_terrain(base_dir, hm_width, hm_height):
    """Generate terrain_class.png from Geography (mat resolution) + GrassApprox (hm resolution).
       Upsample geography to heightmap resolution for a smooth result."""
    geog_path = os.path.join(base_dir, "raw", "geography.bin")
    grass_path = os.path.join(base_dir, "raw", "grass_approx.bin")

    if not os.path.exists(geog_path):
        print("  (geography.bin not found – skipping terrain class map)")
        return

    # Determine mat grid size from geography.bin file size (2 bytes per cell)
    geog_size = os.path.getsize(geog_path) // 2
    mat_w = mat_h = int(geog_size ** 0.5)
    if mat_w * mat_h != geog_size:
        # Try reading meta.json for the actual dimensions
        meta_path = os.path.join(base_dir, "parsed", "meta.json")
        if os.path.exists(meta_path):
            with open(meta_path, "r") as f:
                meta = json.load(f)
            mat_w = meta.get("landRangeX", mat_w)
            mat_h = meta.get("landRangeY", mat_h)
        else:
            print(f"  WARNING: geography.bin has {geog_size} elements, not a perfect square – skipping")
            return
    print(f"  Geography grid: {mat_w}×{mat_h}")

    # Read Geography flags (short per cell, mat resolution)
    with open(geog_path, "rb") as f:
        geog_raw = struct.unpack(f"<{mat_w * mat_h}h", f.read()[:mat_w * mat_h * 2])

    # Read GrassApprox (byte per cell, hm resolution)
    grass = None
    if os.path.exists(grass_path):
        with open(grass_path, "rb") as f:
            grass = f.read()[:hm_width * hm_height]
    else:
        grass = b'\x00' * (hm_width * hm_height)

    # Build terrain image at heightmap resolution
    # Scale factor from mat → hm
    scale_x = hm_width // mat_w
    scale_y = hm_height // mat_h
    if scale_x < 1: scale_x = 1
    if scale_y < 1: scale_y = 1

    img = Image.new('RGB', (hm_width, hm_height))
    pixels = img.load()

    label_counts = {}
    for hm_y in range(hm_height):
        for hm_x in range(hm_width):
            # Map hm pixel to mat cell
            mx = min(hm_x // scale_x, mat_w - 1)
            my = min(hm_y // scale_y, mat_h - 1)
            # Geography is stored row-major
            geo_idx = my * mat_w + mx
            geo_flags = geog_raw[geo_idx]

            grass_val = grass[hm_y * hm_width + hm_x] if hm_y * hm_width + hm_x < len(grass) else 0

            r, g, b, label = classify_terrain(geo_flags, grass_val)
            pixels[hm_x, hm_y] = (r, g, b)
            label_counts[label] = label_counts.get(label, 0) + 1

    img = img.transpose(Image.FLIP_TOP_BOTTOM)

    # Print classification summary
    total_pixels = hm_width * hm_height
    print(f"  Terrain classification ({total_pixels:,} pixels):")
    for label, count in sorted(label_counts.items(), key=lambda x: -x[1]):
        pct = 100.0 * count / total_pixels
        print(f"    {label:20s}     {count:>10,}  ({pct:5.1f}%)")

    # Save PNG
    png_path = os.path.join(base_dir, "parsed", "terrain_class.png")
    img.save(png_path, "PNG")
    print(f"Saved {png_path}  ({hm_width}×{hm_height})")

    # Save JPEG preview (smaller)
    jpg_path = os.path.join(base_dir, "parsed", "terrain_class.jpg")
    img.save(jpg_path, "JPEG", quality=90)
    print(f"Saved {jpg_path}  (JPEG preview)")

    # Generate legend text file
    legend_path = os.path.join(base_dir, "parsed", "terrain_class_legend.txt")
    with open(legend_path, "w") as f:
        f.write("Terrain Class Legend\n")
        f.write("====================\n")
        f.write(f"{'Color':>8}  {'Label':20s}  Pixel count\n")
        f.write(f"{'-----':>8}  {'-----':20s}  -----------\n")
        for (r, g, b), label in LEGEND_ITEMS:
            count = label_counts.get(label.replace(" ", "_"), 0)
            hex_color = f"#{r:02X}{g:02X}{b:02X}"
            f.write(f"{hex_color:>8}  {label:20s}  {count:>10,}\n")
    print(f"Saved {legend_path}")


def convert_geography(base_dir, width, height):
    bin_path = os.path.join(base_dir, "raw", "geography.bin")
    if not os.path.exists(bin_path):
        return

    png_path = os.path.join(base_dir, "parsed", "geography.png")
    with open(bin_path, "rb") as f:
        shorts = struct.unpack(f"<{width*height}h", f.read()[:width*height*2])

    img = Image.new('RGB', (width, height))
    pixels = img.load()
    idx = 0
    for y in range(height):
        for x in range(width):
            val = shorts[idx]

            # Extract flags
            min_depth = val & 0b11
            is_forest = ((val >> 3) & 0b1) > 0
            is_road = ((val >> 4) & 0b1) > 0
            max_depth = (val >> 5) & 0b11

            r, g, b = 0, 0, 0

            if is_road:
                r, g, b = 128, 128, 128
            elif max_depth > 0 or min_depth > 0:
                b = min(255, 100 + max_depth * 50)
            elif is_forest:
                g = 150
            else:
                r, g, b = 30, 30, 30  # Base terrain

            pixels[x, y] = (r, g, b)
            idx += 1

    img = img.transpose(Image.FLIP_TOP_BOTTOM)
    img.save(png_path)
    print(f"Saved {png_path}")


# ── Entry point ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 6:
        print("Usage: convert_pngs.py <base_dir> <hm_width> <hm_height> <mat_width> <mat_height>")
        sys.exit(1)

    base_dir = sys.argv[1]
    hm_w, hm_h = int(sys.argv[2]), int(sys.argv[3])
    mat_w, mat_h = int(sys.argv[4]), int(sys.argv[5])

    convert_heightmap(base_dir, hm_w, hm_h)
    convert_heightmap_grayscale(base_dir, hm_w, hm_h)
    convert_material_mask(base_dir, mat_w, mat_h)

    # New extractions
    convert_byte_palette(base_dir, "sound_map.bin", mat_w, mat_h, "sound_map.png")
    convert_geography(base_dir, mat_w, mat_h)
    convert_byte_grayscale(base_dir, "grass_approx.bin", hm_w, hm_h, "grass_approx.png")
    convert_byte_palette(base_dir, "prim_tex.bin", hm_w, hm_h, "prim_tex.png")
    convert_byte_palette(base_dir, "persistent.bin", mat_w, mat_h, "persistent.png")

    # NEW: Meaningful classified terrain map
    convert_primary_terrain(base_dir, hm_w, hm_h)