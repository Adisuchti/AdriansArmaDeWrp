"""
Render roads from Shapefiles (roads.shp, roads.dbf, RoadsLib.cfg) if they exist,
or fallback to roadnet.json exported by WrpAnalyzer, producing roads.png and updating roadnet.json.

Usage: python render_roads.py <roadnet.json_path> <output_dir>

Road colors match the Arma 3 SVG map export conventions:
  - Tracks (dirt paths):  #D6C2A6 -> (214, 194, 166)
  - Roads (standard):    #B2B2B2 -> (178, 178, 178)
  - Main Roads (highway): #E6804C -> (230, 128, 76)
"""
import json
import sys
import os
import re
import struct
from PIL import Image, ImageDraw

ROAD_COLORS = {
    "track":    (214, 194, 166, 255),
    "road":     (178, 178, 178, 255),
    "mainRoad": (230, 128, 76, 255),
}

ROAD_WIDTHS = {
    "track":    2,
    "road":     4,
    "mainRoad": 6,
}

def parse_roadslib(cfg_path):
    if not os.path.exists(cfg_path):
        return {}
    
    with open(cfg_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
        
    road_classes = {}
    pattern = re.compile(r'class\s+Road(\d+)\s*\{(.*?)\}', re.DOTALL | re.IGNORECASE)
    for match in pattern.finditer(content):
        road_id = int(match.group(1))
        class_content = match.group(2)
        
        map_match = re.search(r'map\s*=\s*"([^"]+)"', class_content, re.IGNORECASE)
        map_type = map_match.group(1) if map_match else "road"
        
        width_match = re.search(r'width\s*=\s*([\d\.]+)', class_content, re.IGNORECASE)
        width = float(width_match.group(1)) if width_match else 10.0
        
        if map_type == "main road":
            map_type = "mainRoad"
        elif map_type not in ["road", "track", "mainRoad"]:
            map_type = "road"
            
        road_classes[road_id] = {
            "type": map_type,
            "width": width
        }
    return road_classes

def parse_dbf(dbf_path):
    if not os.path.exists(dbf_path):
        return []
        
    with open(dbf_path, 'rb') as f:
        header = f.read(32)
        if len(header) < 32:
            return []
        version, yy, mm, dd, num_records, header_size, record_size = struct.unpack('<BBBBIHH', header[:12])
        
        fields = []
        while True:
            b = f.read(1)
            if b == b'\x0d' or not b:
                break
            field_data = b + f.read(31)
            name = field_data[:11].split(b'\x00')[0].decode('ascii', errors='ignore').strip()
            field_type = chr(field_data[11])
            length = field_data[16]
            fields.append((name, field_type, length))
            
        f.seek(header_size)
        records = []
        for _ in range(num_records):
            rec_data = f.read(record_size)
            if len(rec_data) < record_size:
                break
            deleted = rec_data[0] == ord('*')
            if deleted:
                continue
            
            record = {}
            offset = 1
            for name, f_type, f_len in fields:
                val_bytes = rec_data[offset : offset + f_len]
                offset += f_len
                val_str = val_bytes.decode('ascii', errors='ignore').strip()
                record[name] = val_str
            records.append(record)
            
        return records

def parse_shp(shp_path):
    if not os.path.exists(shp_path):
        return []
        
    with open(shp_path, 'rb') as f:
        header = f.read(100)
        if len(header) < 100:
            return []
        file_length = struct.unpack('>i', header[24:28])[0] * 2
        
        shapes = []
        offset = 100
        while offset < file_length:
            f.seek(offset)
            rec_header = f.read(8)
            if len(rec_header) < 8:
                break
            rec_num, content_len = struct.unpack('>ii', rec_header)
            content_len *= 2
            
            rec_content = f.read(content_len)
            if len(rec_content) < content_len:
                break
                
            rec_shape_type = struct.unpack('<i', rec_content[0:4])[0]
            if rec_shape_type == 3: # Polyline
                xmin, ymin, xmax, ymax = struct.unpack('<dddd', rec_content[4:36])
                num_parts, num_points = struct.unpack('<ii', rec_content[36:44])
                
                parts = list(struct.unpack(f'<{num_parts}i', rec_content[44 : 44 + num_parts * 4]))
                
                points_offset = 44 + num_parts * 4
                points = []
                for p in range(num_points):
                    px, py = struct.unpack('<dd', rec_content[points_offset + p * 16 : points_offset + p * 16 + 16])
                    points.append((px, py))
                    
                shapes.append({
                    "rec_num": rec_num,
                    "bbox": (xmin, ymin, xmax, ymax),
                    "parts": parts,
                    "points": points
                })
            offset += 8 + content_len
            
        return shapes

def render_roads(roadnet_json_path, output_dir, web_dir=None):
    # Try to find Shapefiles in raw/roads relative to output_dir
    raw_roads_dir = os.path.abspath(os.path.join(output_dir, "../raw/roads"))
    shp_path = os.path.join(raw_roads_dir, "roads.shp")
    dbf_path = os.path.join(raw_roads_dir, "roads.dbf")
    cfg_path = os.path.join(raw_roads_dir, "RoadsLib.cfg")
    
    use_shapefiles = os.path.exists(shp_path) and os.path.exists(dbf_path)
    
    # Read base config map size
    map_size = 30720
    if os.path.exists(roadnet_json_path):
        try:
            with open(roadnet_json_path, 'r') as f:
                base_data = json.load(f)
                map_size = base_data.get("mapSize", 30720)
        except Exception:
            pass

    roads_data = []

    if use_shapefiles:
        print("Parsing Shapefile road network...")
        shapes = parse_shp(shp_path)
        records = parse_dbf(dbf_path)
        road_classes = parse_roadslib(cfg_path)
        
        print(f"Loaded {len(shapes)} shapes and {len(records)} DBF records.")
        
        if len(shapes) > 0 and len(shapes) == len(records):
            # Calculate UTM offsets automatically
            all_x = [pt[0] for s in shapes for pt in s["points"]]
            all_y = [pt[1] for s in shapes for pt in s["points"]]
            min_x = min(all_x) if all_x else 0
            min_y = min(all_y) if all_y else 0
            
            offset_x = (int(min_x) // 100000) * 100000
            offset_y = (int(min_y) // 100000) * 100000
            print(f"Auto-detected UTM coordinates: min_x={min_x:.1f}, min_y={min_y:.1f}. Applying offsets: offset_x={offset_x}, offset_y={offset_y}")
            
            for i, shape in enumerate(shapes):
                record = records[i]
                road_id = int(record.get('ID', 1))
                road_meta = road_classes.get(road_id, {"type": "road", "width": 10.0})
                
                # Apply offset to local coordinates
                local_pts = [[pt[0] - offset_x, pt[1] - offset_y] for pt in shape["points"]]
                
                roads_data.append({
                    "type": road_meta["type"],
                    "width": road_meta["width"],
                    "pts": local_pts,
                    "p3d": f"roads_f\\roads_ae\\{record.get('__LAYER', '')}_road_{road_id}.p3d"
                })
                
            # Overwrite roadnet.json with full shapefile road network
            roadnet_export = {
                "mapSize": map_size,
                "roads": roads_data
            }
            with open(roadnet_json_path, 'w') as f:
                json.dump(roadnet_export, f)
            print(f"Updated roadnet.json with {len(roads_data)} shapefile roads.")
            
            # Also copy to the web viewer directory
            if web_dir and os.path.exists(web_dir):
                web_roadnet_path = os.path.join(web_dir, "roadnet.json")
                with open(web_roadnet_path, 'w') as f:
                    json.dump(roadnet_export, f)
                print(f"Copied updated roadnet.json to {web_roadnet_path}")
        else:
            print("Warning: Shapefile and DBF record count mismatch, falling back to WRP roadnet.")
            use_shapefiles = False

    if not use_shapefiles:
        # Fallback to loading existing roadnet.json (which contains WRP roadnet data)
        print("Falling back to WRP roadnet.json data...")
        if os.path.exists(roadnet_json_path):
            try:
                with open(roadnet_json_path, 'r') as f:
                    data = json.load(f)
                    # WRP roadnet format uses 'roads' or 'road_links'
                    raw_links = data.get("roads", []) or data.get("road_links", [])
                    for link in raw_links:
                        roads_data.append({
                            "type": link.get("type", "road"),
                            "width": link.get("width", 10.0),
                            "pts": link.get("pts", []) or link.get("positions", [])
                        })
            except Exception as e:
                print(f"Error reading fallback roadnet: {e}")

    if not roads_data:
        print("No road data found. skipping rendering roads.png.")
        return

    # Render PNG
    img_size = 2048
    scale = img_size / map_size

    img = Image.new("RGBA", (img_size, img_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Draw in order: tracks first, roads, main roads on top
    draw_order = ["track", "road", "mainRoad"]
    
    for road_type in draw_order:
        color = ROAD_COLORS.get(road_type, (178, 178, 178, 255))
        width = ROAD_WIDTHS.get(road_type, 2)
        
        for link in roads_data:
            if link.get("type") != road_type:
                continue

            pts = link.get("pts", [])
            if len(pts) >= 2:
                pixel_pts = []
                for pt in pts:
                    px = int(pt[0] * scale)
                    py = img_size - int(pt[1] * scale) # Flip Y
                    pixel_pts.append((px, py))

                for i in range(len(pixel_pts) - 1):
                    draw.line([pixel_pts[i], pixel_pts[i + 1]], fill=color, width=width)
            elif len(pts) == 1:
                # Single point fallback (draw dot)
                pt = pts[0]
                px = int(pt[0] * scale)
                py = img_size - int(pt[1] * scale)
                r = max(1, width)
                draw.ellipse([px - r, py - r, px + r, py + r], fill=color)

    out_path = os.path.join(output_dir, "roads.png")
    img.save(out_path)
    print(f"Saved {out_path} ({img_size}x{img_size})")

    # Copy PNG to web viewer dir if provided
    if web_dir and os.path.exists(web_dir):
        web_png_path = os.path.join(web_dir, "roads.png")
        img.save(web_png_path)
        print(f"Copied roads.png to {web_png_path}")

    # Stats
    type_counts = {}
    for link in roads_data:
        t = link.get("type", "unknown")
        type_counts[t] = type_counts.get(t, 0) + 1
    for t, c in sorted(type_counts.items()):
        print(f"  {t}: {c} links/polylines")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python render_roads.py <roadnet.json_path> <output_dir> [web_dir]")
        sys.exit(1)

    web_dir_arg = sys.argv[3] if len(sys.argv) > 3 else None
    render_roads(sys.argv[1], sys.argv[2], web_dir_arg)
