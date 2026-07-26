import http.server
import socketserver
import os
import json
from urllib.parse import urlparse, unquote

PORT = 8000
CONFIG_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'config.json'))
try:
    with open(CONFIG_PATH, 'r') as f:
        config = json.load(f)
        EXPORTS_DIR = config.get('exports_dir')
except Exception as e:
    print(f"Failed to load config.json: {e}")
    EXPORTS_DIR = os.path.join(os.path.expanduser('~'), 'Documents', 'Arma3MapExports')

MODELS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts', 'converted_models'))

class MapServer(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        # 1. API: List all available maps
        if path == '/api/maps':
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

        # 2. Dynamic Map Assets: /map/Stratis/heightmap.png
        if path.startswith('/map/'):
            parts = path.split('/')
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
                        self.wfile.write(f.read())
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
                    self.wfile.write(f.read())
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

with socketserver.TCPServer(("", PORT), MapServer) as httpd:
    print(f"Serving UI at http://localhost:{PORT}")
    print(f"Loading maps from {EXPORTS_DIR}")
    httpd.serve_forever()
