#!/usr/bin/env python3
"""Serve FMG-standalone.html at / so it can be previewed in a browser."""
import http.server, socketserver, os

HERE = os.path.dirname(os.path.abspath(__file__))
FILE = "FMG-standalone.html"

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html", "/" + FILE):
            self.path = "/" + FILE
        return super().do_GET()

with socketserver.TCPServer(("0.0.0.0", 8000), Handler) as httpd:
    print("Serving FMG-standalone.html on 0.0.0.0:8000")
    httpd.serve_forever()
