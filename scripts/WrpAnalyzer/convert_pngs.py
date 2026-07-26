import struct
import os
import sys
from PIL import Image

def convert_heightmap(base_dir, width, height):
    bin_path = os.path.join(base_dir, "raw", "heightmap.bin")
    if not os.path.exists(bin_path):
        return
        
    png_path = os.path.join(base_dir, "parsed", "heightmap.png")
    
    with open(bin_path, "rb") as f:
        floats = struct.unpack(f"<{width*height}f", f.read())
        
    img = Image.new('L', (width, height))
    pixels = img.load()
    
    min_h = min(floats)
    max_h = max(floats)
    
    idx = 0
    for y in range(height):
        for x in range(width):
            scaled = int((floats[idx] - min_h) / (max_h - min_h) * 255)
            pixels[x, y] = scaled
            idx += 1
            
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
    random.seed(42) # Deterministic colors
    
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
    if not os.path.exists(bin_path): return
        
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
    if not os.path.exists(bin_path): return
        
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
    if not os.path.exists(bin_path): return
        
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
                r, g, b = 30, 30, 30 # Base terrain
                
            pixels[x, y] = (r, g, b)
            idx += 1
            
    img = img.transpose(Image.FLIP_TOP_BOTTOM)
    img.save(png_path)
    print(f"Saved {png_path}")

if __name__ == "__main__":
    if len(sys.argv) < 6:
        print("Usage: convert_pngs.py <base_dir> <hm_width> <hm_height> <mat_width> <mat_height>")
        sys.exit(1)
        
    base_dir = sys.argv[1]
    hm_w, hm_h = int(sys.argv[2]), int(sys.argv[3])
    mat_w, mat_h = int(sys.argv[4]), int(sys.argv[5])
    
    convert_heightmap(base_dir, hm_w, hm_h)
    convert_material_mask(base_dir, mat_w, mat_h)
    
    # New extractions
    convert_byte_palette(base_dir, "sound_map.bin", mat_w, mat_h, "sound_map.png")
    convert_geography(base_dir, mat_w, mat_h)
    convert_byte_grayscale(base_dir, "grass_approx.bin", hm_w, hm_h, "grass_approx.png")
    convert_byte_palette(base_dir, "prim_tex.bin", hm_w, hm_h, "prim_tex.png")
    convert_byte_palette(base_dir, "persistent.bin", mat_w, mat_h, "persistent.png")
