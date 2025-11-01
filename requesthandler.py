from http import HTTPStatus
import os
import azul
import importlib


def do_GET(self, static):
    if os.path.exists("static" + self.url.path):
        return static.do_GET()
    elif self.url.path == "/state":
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(azul.get_state().encode("utf-8"))
    else:
        self.send_error(HTTPStatus.NOT_FOUND, "File not found")


def do_POST(self):
    if self.url.path == "/reset":
        importlib.reload(azul)
        self.send_response(204)
        self.wfile.write("".encode())
    elif self.url.path == "/start":
        azul.start()
        self.send_response(204)
        self.wfile.write("".encode())
    elif self.url.path == "/action":
        azul.set_action(**self.form_data)
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(azul.get_state().encode("utf-8"))
    else:
        self.send_error(HTTPStatus.NOT_FOUND, "File not found")
