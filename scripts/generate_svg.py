import os
import sys
import json
import argparse
import numpy as np
from PIL import Image

# Ensure matplotlib runs headlessly
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import math

def classify_object(cls_name: str, classification: dict) -> str:
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

def get_elevation_array(heightmap_path, min_height, max_height):
    print(f"Loading heightmap from {heightmap_path}...")
    img = Image.open(heightmap_path)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    
    img_arr = np.array(img, dtype=np.float32)
    
    # Check if it is grayscale encoded
    # If R == G == B for the whole image (or a significant part), we might use the fast path, 
    # but let's just do vectorized math for the 24-bit formula.
    
    # R, G, B are the channels
    r = img_arr[:, :, 0]
    g = img_arr[:, :, 1]
    b = img_arr[:, :, 2]
    
    # Detect if grayscale
    is_grayscale = np.all(r == g) and np.all(g == b)
    
    if is_grayscale:
        normalized = r / 255.0
    else:
        # val_24 = (r << 16) | (g << 8) | b
        # normalized = val_24 / 16777215.0
        val_24 = (r * 65536.0) + (g * 256.0) + b
        normalized = val_24 / 16777215.0
        
    elevations = min_height + (normalized * (max_height - min_height))
    return elevations, img.width, img.height

def write_svg_header(f, map_size):
    f.write(f'<svg xmlns="http://www.w3.org/2000/svg" width="{map_size}" height="{map_size}">\n')
    f.write('<defs>\n')
    f.write('<desc>Arma 3 Map SVG Export with Contours</desc>\n')
    
    # Gradients
    gradients = [
        ('colorSea', '#C7E6FC'),
        ('colorLand', '#DFDFDF'),
        ('colorCountlines', '#D1BA94'),
        ('colorCountlinesMain', '#A67345'),
        ('colorRoads', '#B2B2B2'),
        ('colorMainRoads', '#E6804C'),
        ('colorTracks', '#D6C2A6'),
    ]
    
    for gradient_id, color in gradients:
        f.write(f'<linearGradient id="{gradient_id}" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="{color}" /></linearGradient>\n')
        
    f.write('<style type="text/css"><![CDATA[\n')
    f.write('  polyline { fill: none; stroke-linecap: round; stroke-linejoin: round; }\n')
    f.write('  path { fill: none; stroke-linecap: round; stroke-linejoin: round; }\n')
    f.write('  .land { fill: url(#colorLand); stroke: none; }\n')
    f.write('  .contour { stroke: url(#colorCountlines); stroke-width: 1; }\n')
    f.write('  .contour-main { stroke: url(#colorCountlinesMain); stroke-width: 2; }\n')
    f.write('  .road { stroke: url(#colorRoads); stroke-width: 10; }\n')
    f.write('  .mainroad { stroke: url(#colorMainRoads); stroke-width: 14; }\n')
    f.write('  .track { stroke: url(#colorTracks); stroke-width: 5; }\n')
    f.write('  .buildings { fill: #38bdf8; stroke: #0284c7; stroke-width: 0.5; }\n')
    f.write('  .nature { fill: #22c55e; stroke: #16a34a; stroke-width: 0.5; }\n')
    f.write('  .clutter { fill: #78716c; stroke: none; }\n')
    f.write('  .structures { fill: #64748b; stroke: none; }\n')
    f.write('  .lamps { fill: #facc15; stroke: none; }\n')
    
    # Text styles
    f.write('  .place-name { text-anchor: middle; font-family: "Segoe UI", Arial, sans-serif; fill: #1e293b; paint-order: stroke; stroke: #ffffff; stroke-width: 3px; font-weight: bold; }\n')
    f.write('  .NameCityCapital { font-size: 180px; text-transform: uppercase; }\n')
    f.write('  .NameCity { font-size: 140px; text-transform: uppercase; }\n')
    f.write('  .NameVillage { font-size: 100px; }\n')
    f.write('  .NameLocal { font-size: 80px; font-style: italic; font-weight: normal; stroke-width: 2px; }\n')
    f.write('  .Hill { font-size: 70px; font-style: italic; font-weight: normal; fill: #475569; stroke-width: 2px; }\n')
    f.write(']]></style>\n')
    f.write('</defs>\n')
    f.write('<g id="terrain">\n')
    f.write(f'<rect x="0" y="0" height="{map_size}" width="{map_size}" fill="url(#colorSea)"/>\n')

def extract_and_write_contours(f, elevations, map_size, img_width, img_height, contour_interval=10, main_contour_interval=50):
    print("Generating contours...")
    scale_x = map_size / img_width
    scale_y = map_size / img_height
    
    min_elev = np.min(elevations)
    max_elev = np.max(elevations)
    
    # 1. Landmass (Elevation 0)
    # We use a slightly positive value to ensure it's above sea level
    print("Extracting landmass (0m contour)...")
    cs_land = plt.contour(elevations, levels=[0.0])
    
    paths = cs_land.get_paths()
    if paths:
        for path in paths:
            for polygon in path.to_polygons():
                if len(polygon) < 3:
                    continue
                
                # Format points
                pts = []
                for v in polygon:
                    vx = v[0] * scale_x
                    vy = v[1] * scale_y
                    pts.append(f"{vx:.1f},{vy:.1f}")
                    
                pts_str = " ".join(pts)
                f.write(f'<polygon class="land" points="{pts_str}" />\n')
            
    # 2. Elevation Contours
    # Create levels
    start_level = np.ceil(max(min_elev, 0) / contour_interval) * contour_interval
    if start_level == 0:
        start_level = contour_interval
        
    levels = np.arange(start_level, max_elev, contour_interval)
    
    print(f"Extracting elevation contours (intervals of {contour_interval}m)...")
    cs = plt.contour(elevations, levels=levels)
    
    total_lines = 0
    for path, level in zip(cs.get_paths(), cs.levels):
        is_main = (level % main_contour_interval == 0)
        css_class = "contour-main" if is_main else "contour"
        
        for polygon in path.to_polygons():
            if len(polygon) < 2:
                continue
                
            pts = []
            for v in polygon:
                vx = v[0] * scale_x
                vy = v[1] * scale_y
                pts.append(f"{vx:.1f},{vy:.1f}")
                
            pts_str = " ".join(pts)
            f.write(f'<polyline class="{css_class}" points="{pts_str}" />\n')
            total_lines += 1
            
    print(f"Wrote {total_lines} contour lines.")
    
def render_roads(f, roadnet_path, map_size):
    if not os.path.exists(roadnet_path):
        print("roadnet.json not found, skipping roads.")
        return
        
    print(f"Rendering roads from {roadnet_path}...")
    with open(roadnet_path, "r", encoding="utf-8") as rf:
        roadnet = json.load(rf)
        
    roads = roadnet.get("roads", [])
    data_map_size = roadnet.get("mapSize", map_size)
    
    # Scale from Arma coordinates to SVG coordinates.
    # If the SVG is built with X=ArmaX, Y=SVG_TopDown_Y(which is mapSize-ArmaY)
    
    for road in roads:
        pts = road.get("pts", [])
        if len(pts) < 2:
            continue
            
        road_type = road.get("type", "road")
        css_class = "road"
        if road_type == "mainRoad":
            css_class = "mainroad"
        elif road_type == "track":
            css_class = "track"
            
        svg_pts = []
        for pt in pts:
            # Arma world coords
            arma_x = pt[0]
            arma_y = pt[1]
            
            svg_x = arma_x * (map_size / data_map_size)
            svg_y = (data_map_size - arma_y) * (map_size / data_map_size)
            svg_pts.append(f"{svg_x:.1f},{svg_y:.1f}")
            
        pts_str = " ".join(svg_pts)
        f.write(f'<polyline class="{css_class}" points="{pts_str}" />\n')

def render_objects(f, objects_file: str, map_size: float, classification: dict):
    if not os.path.exists(objects_file):
        print("objects.json not found, skipping objects.")
        return
        
    print(f"Rendering objects from {objects_file}...")
    file_size = os.path.getsize(objects_file)
    
    with open(objects_file, "rb") as bf:
        accumulated = b''
        array_start = -1
        while True:
            chunk = bf.read(8192)
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

        bf.seek(array_start + 1)
        decoder = json.JSONDecoder()
        buffer = ''
        count = 0
        bytes_read = array_start + 1

        while True:
            chunk = bf.read(65536)
            if not chunk:
                break
            try:
                text = chunk.decode('utf-8')
            except UnicodeDecodeError:
                text = chunk.decode('utf-8', errors='replace')
            buffer += text
            bytes_read += len(chunk)

            while True:
                stripped = buffer.lstrip(' \t\n\r,')
                if not stripped:
                    buffer = ''
                    break
                if stripped[0] == ']':
                    print(f"  Objects: {count:,} total processed.")
                    return  # end of array

                try:
                    obj, end = decoder.raw_decode(stripped)
                except json.JSONDecodeError:
                    break

                buffer = stripped[end:]

                x = obj.get("x")
                y = obj.get("y")
                if x is not None and y is not None:
                    cat = classify_object(obj.get("class", ""), classification)
                    
                    w = abs((obj.get("w") or 1) * (obj.get("scaleX") or 1))
                    l = abs((obj.get("l") or 1) * (obj.get("scaleZ") or 1))
                    
                    # Artificially boost size of very small objects so they are visible
                    w = max(w, 2.0)
                    l = max(l, 2.0)
                    
                    dir_deg = obj.get("dir") or 0
                    
                    svg_x = x
                    svg_y = map_size - y
                    
                    rx = svg_x - (w / 2)
                    ry = svg_y - (l / 2)
                    
                    if cat == "nature" and max(w, l) < 5:
                        rad = max(w, l) / 2
                        f.write(f'<circle class="{cat}" cx="{svg_x:.1f}" cy="{svg_y:.1f}" r="{rad:.1f}" />\n')
                    else:
                        f.write(f'<rect class="{cat}" x="{rx:.1f}" y="{ry:.1f}" width="{w:.1f}" height="{l:.1f}" transform="rotate({dir_deg:.1f}, {svg_x:.1f}, {svg_y:.1f})" />\n')

                count += 1
                if count % 200000 == 0:
                    pct = 100.0 * bytes_read / file_size if file_size else 0
                    print(f"  Objects: {count:,} parsed ({min(pct, 100):.0f}% of file)...")

        print(f"  Objects: {count:,} total processed.")

def render_names(f, names_path, map_size):
    if not os.path.exists(names_path):
        return
        
    print(f"Rendering place names from {names_path}...")
    f.write('<g id="place-names">\n')
    
    with open(names_path, "r", encoding="utf-8") as nf:
        names = json.load(nf)
        
    for place in names:
        x = place.get("x", 0)
        y = place.get("y", 0)
        name = place.get("name", "")
        p_type = place.get("type", "")
        
        if not name:
            continue
            
        # SVG coordinates (Y is flipped in SVG relative to map coordinates)
        svg_y = map_size - y
        
        # Determine CSS class based on type
        cls = "place-name"
        if p_type:
            cls += f" {p_type}"
            
        f.write(f'  <text x="{x:.1f}" y="{svg_y:.1f}" class="{cls}">{name}</text>\n')
        
    f.write('</g>\n')

def main():
    parser = argparse.ArgumentParser(description="Generate SVG Map with Contours from Arma 3 exports.")
    parser.add_argument("map_dir", help="Path to the extracted map directory (e.g. Altis_WRP)")
    parser.add_argument("--output", help="Output SVG file path (default: <MapName>_Map.svg)", default=None)
    parser.add_argument("--interval", type=int, default=10, help="Contour interval in meters (default: 10)")
    parser.add_argument("--main-interval", type=int, default=50, help="Main contour interval in meters (default: 50)")
    parser.add_argument("--no-names", action="store_true", help="Skip rendering place names on the map")
    
    args = parser.parse_args()
    
    map_dir = os.path.abspath(args.map_dir)
    map_name = os.path.basename(map_dir.rstrip("\\/"))
    
    meta_path = os.path.join(map_dir, "meta.json")
    if not os.path.exists(meta_path):
        print(f"Error: meta.json not found in {map_dir}")
        sys.exit(1)
        
    with open(meta_path, "r", encoding="utf-8") as mf:
        meta = json.load(mf)
        
    map_size = meta.get("mapSize", 8192)
    min_height = meta.get("minHeight", -200)
    max_height = meta.get("maxHeight", 500)
    
    # Load classification
    script_dir = os.path.dirname(os.path.abspath(__file__))
    class_path = os.path.join(script_dir, "..", "web", "classification.json")
    classification = {}
    if os.path.exists(class_path):
        with open(class_path, "r", encoding="utf-8") as cf:
            classification = json.load(cf)
            
    heightmap_path = os.path.join(map_dir, "heightmap.png")
    if not os.path.exists(heightmap_path):
        print(f"Error: heightmap.png not found in {map_dir}")
        sys.exit(1)
        
    out_path = args.output
    if not out_path:
        out_path = os.path.join(map_dir, f"{map_name}_Map.svg")
        
    print(f"Starting SVG generation for {map_name} (Size: {map_size}m)")
    
    # Process
    elevations, img_width, img_height = get_elevation_array(heightmap_path, min_height, max_height)
    
    print(f"Writing SVG to {out_path}...")
    with open(out_path, "w", encoding="utf-8") as f:
        write_svg_header(f, map_size)
        
        # 1. Contours and Landmass
        extract_and_write_contours(f, elevations, map_size, img_width, img_height, args.interval, args.main_interval)
        
        # 2. Roads
        roadnet_path = os.path.join(map_dir, "roadnet.json")
        render_roads(f, roadnet_path, map_size)
        
        # 3. Objects
        objects_path = os.path.join(map_dir, "objects.json")
        render_objects(f, objects_path, map_size, classification)
        
        # 4. Names
        if not args.no_names:
            names_path = os.path.join(map_dir, "names.json")
            render_names(f, names_path, map_size)
        else:
            print("  (--no-names: skipping place names)")
        
        f.write('</g>\n')
        f.write('</svg>\n')
        
    print("Done!")

if __name__ == "__main__":
    main()
