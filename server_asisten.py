"""
server_asisten.py — Asisten PC Versi Chrome
============================================
Python berjalan sebagai WebSocket server di background.
Chrome membuka asisten.html sebagai "telinga" (Web Speech API).
Python menerima teks dari Chrome dan mengeksekusi perintah native Windows.
"""

import asyncio
import json
import os
import subprocess
import threading
import webbrowser
import websockets
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import logging

# Matikan log bawaan HTTP server agar terminal bersih
logging.getLogger('http.server').setLevel(logging.ERROR)

# ── Konfigurasi ───────────────────────────────────────────────────────────────
HOST      = "localhost"
PORT      = 8765       # WebSocket
HTTP_PORT = 8766       # HTTP server (agar Chrome ingat izin mic)
HTML_DIR  = Path(__file__).parent
HTML_PATH = HTML_DIR / "asisten.html"

# ── Pemetaan perintah ke aplikasi ─────────────────────────────────────────────
# Kunci    : kata kunci dalam ucapan (lowercase)
# "app"    : nama untuk AppOpener (match_closest)
# "cmd"    : perintah shell langsung (lebih andal untuk UWP/built-in)
# "url"    : buka URL di browser
APP_MAP = {
    "whatsapp"     : {"cmd": "start whatsapp:"},
    "notepad"      : {"cmd": "start notepad"},
    "kalkulator"   : {"cmd": "start calc"},
    "calculator"   : {"cmd": "start calc"},
    "chrome"       : {"app": "chrome"},
    "spotify"      : {"cmd": "start spotify:"},
    "vscode"       : {"app": "visual studio code"},
    "file explorer" : {"cmd": "start explorer"},
    "explorer"     : {"cmd": "start explorer"},
    "word"         : {"app": "microsoft word"},
    "excel"        : {"app": "microsoft excel"},
    "powerpoint"   : {"app": "microsoft powerpoint"},
    "youtube"      : {"url": "https://youtube.com"},
    "google"       : {"url": "https://google.com"},
    "instagram"    : {"url": "https://instagram.com"},
    "gmail"        : {"url": "https://mail.google.com"},
}

# Kata pemicu perintah buka
BUKA_TRIGGERS = ["buka", "open", "jalankan", "aktifkan", "launch"]


def parse_command(text: str):
    """
    Menganalisa teks transkripsi dan mengembalikan aksi yang harus dijalankan.
    Return: dict {"type": "app"/"url"/"unknown", "target": ..., "display": ...}
    """
    text = text.lower().strip()

    # Cek apakah ada kata pemicu "buka X"
    triggered = False
    for trigger in BUKA_TRIGGERS:
        if text.startswith(trigger):
            text = text[len(trigger):].strip()
            triggered = True
            break

    if not triggered:
        return None  # abaikan ucapan yang tidak dimulai dengan pemicu

    # Cocokkan dengan APP_MAP
    for keyword, action in APP_MAP.items():
        if keyword in text:
            return {**action, "display": keyword}

    # Tidak ada yang cocok — coba buka dengan AppOpener secara dinamis
    return {"app": text, "display": text}


def open_cmd(shell_cmd: str) -> str:
    """Jalankan perintah shell langsung (untuk UWP / built-in Windows)."""
    try:
        subprocess.Popen(shell_cmd, shell=True)
        return f"OK (cmd): '{shell_cmd}'"
    except Exception as e:
        return f"GAGAL (cmd): {e}"


def open_app(app_name: str) -> str:
    """Buka aplikasi menggunakan AppOpener, fallback ke shell 'start'."""
    try:
        import appopener
        appopener.open(app_name, match_closest=True, output=False)
        return f"OK: '{app_name}' dibuka."
    except Exception:
        # Fallback: shell start
        try:
            subprocess.Popen(f'start "" "{app_name}"', shell=True)
            return f"OK (fallback shell): '{app_name}'"
        except Exception as e2:
            return f"GAGAL membuka '{app_name}': {e2}"


def open_url(url: str) -> str:
    """Buka URL di browser default."""
    webbrowser.open(url)
    return f"OK: URL '{url}' dibuka di browser."


# ── WebSocket Handler ─────────────────────────────────────────────────────────
async def handler(websocket):
    client_addr = websocket.remote_address
    print(f"[+] Client terhubung: {client_addr}")

    try:
        async for raw_msg in websocket:
            try:
                msg = json.loads(raw_msg)
            except json.JSONDecodeError:
                print(f"[!] Pesan tidak valid (bukan JSON): {raw_msg}")
                continue

            if msg.get("type") != "transcript":
                continue

            text = msg.get("text", "").strip()
            if not text:
                continue

            print(f"[Didengar] {text}")

            action = parse_command(text)
            if action is None:
                print(f"[~] Diabaikan (tidak ada pemicu): {text}")
                continue

            # Eksekusi
            if "url" in action:
                result = open_url(action["url"])
                exec_display = f"Buka URL: {action['display']}"
            elif "cmd" in action:
                result = open_cmd(action["cmd"])
                exec_display = f"Buka: {action['display']}"
            else:
                result = open_app(action["app"])
                exec_display = f"Buka aplikasi: {action['display']}"

            print(f"[Eksekusi] {result}")

            # Kirim feedback ke Chrome
            await websocket.send(json.dumps({
                "type"   : "exec",
                "command": exec_display,
                "result" : result
            }))

    except websockets.exceptions.ConnectionClosedOK:
        print(f"[-] Client terputus (normal): {client_addr}")
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"[-] Client terputus (error): {client_addr} — {e}")


# ── HTTP Server (agar Chrome menyimpan izin mic) ─────────────────────────────
class SilentHTTPHandler(SimpleHTTPRequestHandler):
    """HTTP handler tanpa log di terminal."""
    def log_message(self, format, *args):
        pass  # diam

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HTML_DIR), **kwargs)


def start_http_server():
    server = HTTPServer((HOST, HTTP_PORT), SilentHTTPHandler)
    print(f"[HTTP] Server aktif di http://{HOST}:{HTTP_PORT}")
    server.serve_forever()


# ── Buka Chrome ke asisten.html via localhost ─────────────────────────────────
def launch_browser():
    """
    Buka asisten.html via http://localhost agar Chrome menyimpan izin mic.
    Tampilan --app mode (tanpa address bar).
    """
    url = f"http://{HOST}:{HTTP_PORT}/asisten.html"

    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]

    chrome_exe = None
    for path in chrome_paths:
        if os.path.exists(path):
            chrome_exe = path
            break

    if chrome_exe:
        subprocess.Popen([
            chrome_exe,
            f"--app={url}",
            "--window-size=540,520",
            "--window-position=40,40",
        ])
        print(f"[Browser] Chrome dibuka: {url}")
    else:
        webbrowser.open(url)
        print(f"[Browser] Browser default dibuka: {url}")


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    print("=" * 52)
    print("  Asisten PC — Server WebSocket Aktif")
    print(f"  WS  : ws://{HOST}:{PORT}")
    print(f"  HTTP: http://{HOST}:{HTTP_PORT}")
    print("  Tekan Ctrl+C untuk berhenti.")
    print("=" * 52)

    # Jalankan HTTP server di thread terpisah (daemon)
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()

    # Buka browser setelah server siap
    loop = asyncio.get_event_loop()
    loop.call_later(1.2, launch_browser)

    async with websockets.serve(handler, HOST, PORT):
        await asyncio.Future()  # jalan selamanya


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Server] Dihentikan oleh user.")
