import struct
import os
import sys
import json
import colorsys
from PIL import Image

def generate_deterministic_color(index):
    golden_ratio_conjugate = 0.618033988749895
    hue = (index * golden_ratio_conjugate) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 0.95)
    return (int(r * 255), int(g * 255), int(b * 255))


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


def parse_rvmat_layers(path):
    if not path:
        return []
    normalized = path.replace("\\", "/").lower()
    filename = os.path.basename(normalized)
    if filename.startswith("p_") and "_" in filename:
        parts = filename.split("_")
        if len(parts) >= 3:
            layers = []
            for p in parts[2:]:
                if p.endswith(".rvmat"):
                    p = p[:-6]
                layers.append(p)
            return layers
    if normalized.endswith(".rvmat"):
        normalized = normalized[:-6]
    return [normalized]


def convert_primary_texture(base_dir, hm_width, hm_height, mat_width, mat_height):
    prim_bin_path = os.path.join(base_dir, "raw", "prim_tex.bin")
    mask_bin_path = os.path.join(base_dir, "raw", "material_mask.bin")
    mat_names_path = os.path.join(base_dir, "parsed", "material_names.json")

    if not os.path.exists(prim_bin_path) or not os.path.exists(mask_bin_path) or not os.path.exists(mat_names_path):
        convert_byte_palette(base_dir, "prim_tex.bin", hm_width, hm_height, "prim_tex.png")
        return

    print("  Generating lossless prim_tex.png using material mask...")

    with open(mat_names_path, "r") as f:
        mat_names = json.load(f)

    with open(mask_bin_path, "rb") as f:
        ushorts = struct.unpack(f"<{mat_width*mat_height}H", f.read()[:mat_width*mat_height*2])

    with open(prim_bin_path, "rb") as f:
        bytes_data = struct.unpack(f"<{hm_width*hm_height}B", f.read()[:hm_width*hm_height])

    mat_layers = []
    for path in mat_names:
        mat_layers.append(parse_rvmat_layers(path))

    unique_layers = set()
    resolved_layers = []
    for mat_idx in range(len(mat_names)):
        layers = mat_layers[mat_idx]
        row = []
        for slot_idx in range(256):
            layer_name = layers[slot_idx] if slot_idx < len(layers) else "n"
            row.append(layer_name)
            unique_layers.add(layer_name)
        resolved_layers.append(row)

    unique_layers.discard("n")
    sorted_layers = sorted(list(unique_layers))

    layer_colors = {"n": (0, 0, 0)}
    legend_data = [{"layer": "n", "hex_color": "#000000", "rgb": [0, 0, 0]}]

    for i, layer in enumerate(sorted_layers):
        color = generate_deterministic_color(i + 1)
        layer_colors[layer] = color
        hex_color = f"#{color[0]:02X}{color[1]:02X}{color[2]:02X}"
        legend_data.append({
            "layer": layer,
            "hex_color": hex_color,
            "rgb": list(color)
        })

    scale_x = hm_width // mat_width
    scale_y = hm_height // mat_height
    if scale_x < 1: scale_x = 1
    if scale_y < 1: scale_y = 1

    img = Image.new('RGB', (hm_width, hm_height))
    pixels = img.load()

    for hm_y in range(hm_height):
        hm_row_offset = hm_y * hm_width
        my = min(hm_y // scale_y, mat_height - 1)
        mat_row_offset = my * mat_width

        for hm_x in range(hm_width):
            mx = min(hm_x // scale_x, mat_width - 1)
            mat_idx = ushorts[mat_row_offset + mx]
            slot_idx = bytes_data[hm_row_offset + hm_x]

            if mat_idx < len(resolved_layers):
                layer_name = resolved_layers[mat_idx][slot_idx]
            else:
                layer_name = "n"

            pixels[hm_x, hm_y] = layer_colors[layer_name]

    img = img.transpose(Image.FLIP_TOP_BOTTOM)
    png_path = os.path.join(base_dir, "parsed", "prim_tex.png")
    img.save(png_path)
    print(f"Saved {png_path} (Lossless)")

    legend_path = os.path.join(base_dir, "parsed", "prim_tex_legend.json")
    with open(legend_path, "w", encoding="utf-8") as f:
        json.dump(legend_data, f, indent=2)
    print(f"Saved {legend_path}")


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


def convert_geography(base_dir, width, height):
    bin_path = os.path.join(base_dir, "raw", "geography.bin")
    if not os.path.exists(bin_path):
        return

    png_path = os.path.join(base_dir, "parsed", "geography.png")
    with open(bin_path, "rb") as f:
        shorts = struct.unpack(f"<{width*height}h", f.read()[:width*height*2])

    unique_vals = list(set(shorts))
    unique_vals.sort()
    
    color_map = {}
    legend_data = []
    
    for i, val in enumerate(unique_vals):
        min_depth = val & 0b11
        is_forest = ((val >> 3) & 0b1) > 0
        is_road = ((val >> 4) & 0b1) > 0
        max_depth = (val >> 5) & 0b11
        
        if val == 0:
            color = (30, 30, 30)
        else:
            avg_depth = (min_depth + max_depth) / 2.0
            
            # Map average depth (0 to 3) to a greyscale value (e.g. 50 to 220)
            depth_val = int(50 + (170 * (avg_depth / 3.0)))
            base_depth_color = (depth_val, depth_val, depth_val)
            
            colors_to_mix = [base_depth_color]
            
            if is_forest:
                colors_to_mix.append((0, 120, 0)) # Dark green
                
            if is_road:
                colors_to_mix.append((200, 80, 80)) # Noticeable road color (reddish)
                
            r = sum(c[0] for c in colors_to_mix) // len(colors_to_mix)
            g = sum(c[1] for c in colors_to_mix) // len(colors_to_mix)
            b = sum(c[2] for c in colors_to_mix) // len(colors_to_mix)
            
            color = (r, g, b)
            
        color_map[val] = color
        
        hex_color = f"#{color[0]:02X}{color[1]:02X}{color[2]:02X}"
        legend_data.append({
            "value": val,
            "hex_color": hex_color,
            "rgb": list(color),
            "min_depth": min_depth,
            "max_depth": max_depth,
            "is_forest": is_forest,
            "is_road": is_road
        })

    img = Image.new('RGB', (width, height))
    pixels = img.load()
    idx = 0
    for y in range(height):
        for x in range(width):
            pixels[x, y] = color_map[shorts[idx]]
            idx += 1

    img = img.transpose(Image.FLIP_TOP_BOTTOM)
    img.save(png_path)
    print(f"Saved {png_path}")
    
    legend_path = os.path.join(base_dir, "parsed", "geography_legend.json")
    with open(legend_path, "w", encoding="utf-8") as f:
        json.dump(legend_data, f, indent=2)
    print(f"Saved {legend_path}")


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
    convert_primary_texture(base_dir, hm_w, hm_h, mat_w, mat_h)
    convert_byte_palette(base_dir, "persistent.bin", mat_w, mat_h, "persistent.png")

    