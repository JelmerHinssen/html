from functools import cached_property
from http.cookies import SimpleCookie
from http.server import HTTPServer, SimpleHTTPRequestHandler
from threading import Thread
import time
from urllib.parse import parse_qsl, urlparse
import json
import signal

import requesthandler
import importlib


class WebRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, request, client_address, server) -> None:
        super().__init__(request, client_address, server, directory="static")

    @cached_property
    def url(self):
        return urlparse(self.path)

    @cached_property
    def query_data(self):
        return dict(parse_qsl(self.url.query))

    @cached_property
    def post_data(self):
        content_length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(content_length)

    @cached_property
    def form_data(self):
        return dict(parse_qsl(self.post_data.decode("utf-8")))

    @cached_property
    def cookies(self):
        return SimpleCookie(self.headers.get("Cookie"))

    def get_response(self):
        return json.dumps(
            {
                "path": self.url.path,
                "query_data": self.query_data,
                "post_data": self.post_data.decode("utf-8"),
                "form_data": self.form_data,
                "cookies": {name: cookie.value for name, cookie in self.cookies.items()},
            }
        )

    def do_GET(self):
        requesthandler.do_GET(self, super())

    def do_POST(self):
        requesthandler.do_POST(self)


def handler(a, b):
    print("Sigint")
    exit(1)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, handler)
    server = HTTPServer(("0.0.0.0", 8000), WebRequestHandler)

    def run():
        server.serve_forever()

    Thread(target=run, daemon=True).start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("KeyboardInterrupt")
    finally:
        print("Shutdown")
