from __future__ import annotations

import contextlib
import socket
import threading
import time

import uvicorn
import webview


def free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_server(host: str, port: int, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.25)
            if sock.connect_ex((host, port)) == 0:
                return
        time.sleep(0.1)
    raise RuntimeError("El motor local no pudo iniciar.")


def main() -> None:
    host = "127.0.0.1"
    port = free_port()
    from app.main import app
    config = uvicorn.Config(app, host=host, port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    wait_for_server(host, port)
    webview.create_window(
        "BioStat Studio",
        f"http://{host}:{port}",
        width=1440,
        height=900,
        min_size=(1024, 700),
        confirm_close=True,
    )
    webview.start(debug=False)
    server.should_exit = True


if __name__ == "__main__":
    main()
