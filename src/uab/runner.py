import subprocess
import os
import sys
import requests
import time
from PySide6.QtWidgets import QApplication

from uab.frontend.main_widget import MainWidget
from uab.frontend.main_window import MainWindow
from uab.core.utils import is_macos

_SERVER_PROCESS = None
_SERVER_PORT = 8000
_SERVER_HOST = "127.0.0.1"
_SERVER_URL = f"http://{_SERVER_HOST}:{_SERVER_PORT}"


def run():
    is_houdini = _get_current_dcc() == "hou"

    # Start server (detached process if not already running)
    server_proc = _start_server()
    registration_pid = os.getpid()
    CLIENT_ID = f"{registration_pid}_{_get_current_dcc()}"
    print(
        f"Registering client with PID {registration_pid}, client_id: {CLIENT_ID}")
    requests.post(f"{_SERVER_URL}/register_client",
                  json={"client_id": CLIENT_ID})

    if is_houdini:
        global _SERVER_PROCESS
        _SERVER_PROCESS = server_proc
        result = _start_gui(CLIENT_ID)
        return result
    else:
        result = _start_gui(CLIENT_ID)
        return result


def _start_server():
    """Ensure the FastAPI server is running (spawn detached process if needed)."""
    global _SERVER_PORT, _SERVER_HOST

    if _is_server_alive(_SERVER_URL):
        print("Server already running, reusing existing instance.")
        return None

    print("Starting detached server subprocess...")

    # Detached subprocess
    # Cannot use sys.executable because it will use Houdini's Python interpreter, which will launch a second Houdini instance and not the server.
    PYTHON_BIN = os.environ.get(
        "UAB_PYTHON", "/Users/dev/Projects/uab/.venv/bin/python")
    cmd = [
        PYTHON_BIN,
        "-m",
        "uvicorn",
        "uab.backend.server:app",
        "--host",
        _SERVER_HOST,
        "--port",
        str(_SERVER_PORT),
    ]

    # TODO: support linux
    if not is_macos():
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        creationflags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        server_proc = subprocess.Popen(
            cmd,
            creationflags=creationflags,
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
            close_fds=True,
        )
    else:
        server_proc = subprocess.Popen(
            cmd,
            start_new_session=True,
            stdin=sys.stdin,
            stdout=sys.stdout,
            stderr=sys.stderr,
            close_fds=True,
        )

    # Poll until reachable
    if not _wait_for_server(_SERVER_URL, timeout=10):
        raise RuntimeError("Detached server failed to start in time.")

    print(f"Server started and reachable at {_SERVER_URL}")
    return server_proc


def _is_server_alive(url):
    try:
        r = requests.get(url, timeout=0.25)
        return r.status_code < 500
    except Exception:
        return False


def _wait_for_server(url, timeout=5, tick=0.25):
    """Wait for the server to respond, ensuring it's reachable."""
    start = time.time()
    while time.time() - start < timeout:
        if _is_server_alive(url):
            return True
        time.sleep(tick)
    return False


def unregister_client(client_id: str):
    try:
        current_pid = os.getpid()
        print(f"Unregistering client {client_id} (current PID: {current_pid})")
        response = requests.post(
            f"{_SERVER_URL}/unregister_client", json={"client_id": client_id})
        response.raise_for_status()
        print(f"Successfully unregistered client {client_id}")
    except requests.exceptions.RequestException as e:
        print(f"Error unregistering client {client_id}: {e}")


def _start_gui(client_id: str):
    """Launch the GUI appropriately depending on environment."""
    print("Starting GUI...")
    match _get_current_dcc():
        case "hou":
            return MainWidget("hou", client_id)
        case "desktop":
            app = QApplication(sys.argv)

            def unregister_current_process():
                current_client_id = f"{os.getpid()}_{_get_current_dcc()}"
                unregister_client(current_client_id)
            win = MainWindow(MainWidget("desktop", client_id),
                             unregister_callback=unregister_current_process)
            win.show()
            # This handles Cmd+Q and other times that QApplication.quit() is called.
            app.aboutToQuit.connect(lambda: win._unregister_if_needed())
            exit_code = app.exec()
            return exit_code
        case _:
            pass


def _get_current_dcc():
    """Determine which environment UAB is being launched from."""
    try:
        import hou  # Houdini
        return "hou"
    except ImportError:
        return "desktop"
