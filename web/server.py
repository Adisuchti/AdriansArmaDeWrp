import http.server
import socketserver
import os
import json
import shutil
from urllib.parse import urlparse, unquote, parse_qs

PORT = 8000
CONFIG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'config.json'))
try:
    with open(CONFIG_PATH, 'r') as f:
        config = json.load(f)
        EXPORTS_DIR = config.get('exports_dir')
except Exception as e:
    print(f"Failed to load config.json: {e}")
    EXPORTS_DIR = os.path.join(os.path.expanduser('~'), 'Documents', 'Arma3MapExports')

MODELS_DIR = os.path.join(EXPORTS_DIR, 'models')

class MapServer(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)

        # 1. API: List all available maps
        if path == '/api/maps' or path == '/api/maps.json':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            maps = []
            if os.path.exists(EXPORTS_DIR):
                for item in os.listdir(EXPORTS_DIR):
                    map_path = os.path.join(EXPORTS_DIR, item)
                    if os.path.isdir(map_path):
                        maps.append(item)
            
            self.wfile.write(json.dumps({"maps": maps}).encode())
            return

        # 2. Dynamic Map Assets: /map/Stratis/objects_in_region?minX=&maxX=&minY=&maxY=
        if path.startswith('/map/'):
            parts = path.split('/')
            if len(parts) >= 4 and parts[3] == 'objects_in_region':
                map_name = parts[2]
                self._serve_objects_in_region(map_name, query)
                return

            if len(parts) >= 4 and parts[3] == 'roads_in_region':
                map_name = parts[2]
                self._serve_roads_in_region(map_name, query)
                return

            if len(parts) >= 4:
                map_name = parts[2]
                file_name = parts[3]
                target_file = os.path.join(EXPORTS_DIR, map_name, file_name)
                
                if os.path.exists(target_file):
                    self.send_response(200)
                    if file_name.endswith('.png'):
                        self.send_header('Content-type', 'image/png')
                    elif file_name.endswith('.json'):
                        self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    
                    with open(target_file, 'rb') as f:
                        shutil.copyfileobj(f, self.wfile)
                    return
            
            self.send_error(404, "File not found")
            return

        # 3. Serve GLTF Models: /models/barrelsand_f.glb
        if path.startswith('/models/'):
            # Extract filename and prevent directory traversal
            file_name = os.path.basename(path)
            target_file = os.path.join(MODELS_DIR, file_name)
            
            if os.path.exists(target_file):
                self.send_response(200)
                if file_name.endswith('.glb'):
                    self.send_header('Content-type', 'model/gltf-binary')
                elif file_name.endswith('.gltf'):
                    self.send_header('Content-type', 'model/gltf+json')
                self.end_headers()
                
                with open(target_file, 'rb') as f:
                    shutil.copyfileobj(f, self.wfile)
                return
            
            self.send_error(404, f"Model not found: {file_name}")
            return

        # 4. Serve local frontend files (index.html, style.css, main.js)
        if path == '/' or path.endswith('.html') or path.endswith('.js') or path.endswith('.css'):
            self.send_response(200)
            if path == '/' or path.endswith('.html'): self.send_header('Content-type', 'text/html')
            elif path.endswith('.js'): self.send_header('Content-type', 'application/javascript')
            elif path.endswith('.css'): self.send_header('Content-type', 'text/css')
            self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
            self.end_headers()
            with open(os.path.join(os.path.dirname(__file__), path.lstrip('/')) if path != '/' else os.path.join(os.path.dirname(__file__), 'index.html'), 'rb') as f:
                self.wfile.write(f.read())
            return
            
        return super().do_GET()

    def _serve_objects_in_region(self, map_name, query):
        """Stream-filter objects.json by bounding box, returning only objects in the region as NDJSON."""
        objects_file = os.path.join(EXPORTS_DIR, map_name, 'objects.json')
        if not os.path.exists(objects_file):
            self.send_error(404, f"objects.json not found for map {map_name}")
            return

        try:
            min_x = float(query.get('minX', [None])[0])
            max_x = float(query.get('maxX', [None])[0])
            min_y = float(query.get('minY', [None])[0])
            max_y = float(query.get('maxY', [None])[0])
        except (TypeError, ValueError):
            self.send_error(400, "Missing or invalid query parameters: minX, maxX, minY, maxY required")
            return

        self.send_response(200)
        self.send_header('Content-type', 'application/x-ndjson')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        # Step 1: Find the byte position of '[' after "objects" — read only the file header
        array_start = -1
        with open(objects_file, 'rb') as f:
            accumulated = b''
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
            return

        # Step 2: Stream-parse objects from the file in chunks — never loads the entire file
        decoder = json.JSONDecoder()
        buffer = ''

        with open(objects_file, 'r', encoding='utf-8') as f:
            f.seek(array_start + 1)  # Skip past the '['

            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                buffer += chunk

                while True:
                    # Trim leading whitespace and commas
                    buffer = buffer.lstrip(' \t\n\r,')
                    if not buffer:
                        break
                    if buffer[0] == ']':
                        return  # End of objects array

                    try:
                        obj, end = decoder.raw_decode(buffer)
                    except json.JSONDecodeError:
                        # Incomplete object at chunk boundary — need more data
                        break

                    obj_x = obj.get('x')
                    obj_y = obj.get('y')
                    if obj_x is not None and obj_y is not None:
                        if min_x <= obj_x <= max_x and min_y <= obj_y <= max_y:
                            self.wfile.write(
                                json.dumps(obj, separators=(',', ':')).encode('utf-8') + b'\n'
                            )

                    buffer = buffer[end:]

    def _segment_intersects_bbox(self, p1, p2, min_x, max_x, min_y, max_y):
        """Check if a line segment intersects or is within a bounding box."""
        # Quick check: either endpoint inside bbox
        if (min_x <= p1[0] <= max_x and min_y <= p1[1] <= max_y):
            return True
        if (min_x <= p2[0] <= max_x and min_y <= p2[1] <= max_y):
            return True
        # Check if segment crosses the bbox boundaries
        # Cohen-Sutherland-like checks for any overlap
        seg_min_x = min(p1[0], p2[0])
        seg_max_x = max(p1[0], p2[0])
        seg_min_y = min(p1[1], p2[1])
        seg_max_y = max(p1[1], p2[1])
        if seg_max_x < min_x or seg_min_x > max_x:
            return False
        if seg_max_y < min_y or seg_min_y > max_y:
            return False
        return True

    def _serve_roads_in_region(self, map_name, query):
        """Filter roadnet.json polylines by bounding box, returning only roads that intersect the region."""
        roadnet_file = os.path.join(EXPORTS_DIR, map_name, 'roadnet.json')
        if not os.path.exists(roadnet_file):
            self.send_error(404, f"roadnet.json not found for map {map_name}")
            return

        try:
            min_x = float(query.get('minX', [None])[0])
            max_x = float(query.get('maxX', [None])[0])
            min_y = float(query.get('minY', [None])[0])
            max_y = float(query.get('maxY', [None])[0])
        except (TypeError, ValueError):
            self.send_error(400, "Missing or invalid query parameters: minX, maxX, minY, maxY required")
            return

        try:
            with open(roadnet_file, 'r', encoding='utf-8') as f:
                roadnet = json.load(f)
        except Exception as e:
            self.send_error(500, f"Failed to read roadnet.json: {e}")
            return

        raw_roads = roadnet.get('roads', [])
        matching_roads = []

        for road in raw_roads:
            pts = road.get('pts', [])
            if len(pts) < 2:
                continue

            # Check if any segment of the road intersects the bbox
            intersects = False
            for i in range(len(pts) - 1):
                if self._segment_intersects_bbox(pts[i], pts[i + 1], min_x, max_x, min_y, max_y):
                    intersects = True
                    break

            if intersects:
                matching_roads.append({
                    "type": road.get("type", "road"),
                    "width": road.get("width", 10.0),
                    "pts": pts
                })

        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"roads": matching_roads}).encode())

with socketserver.TCPServer(("", PORT), MapServer) as httpd:
    print(f"Serving UI at http://localhost:{PORT}")
    print(f"Loading maps from {EXPORTS_DIR}")
    httpd.serve_forever()