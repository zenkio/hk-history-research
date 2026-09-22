import http.server
import socketserver
import os
import sys

# Usage: python3 serve_preview.py [directory] [port]
directory = sys.argv[1] if len(sys.argv) > 1 else "public"
port = int(sys.argv[2]) if len(sys.argv) > 2 else 8000

os.chdir(directory)
Handler = http.server.SimpleHTTPRequestHandler

with socketserver.TCPServer(("", port), Handler) as httpd:
    print(f"Serving {directory} at http://localhost:{port}")
    httpd.serve_forever()
