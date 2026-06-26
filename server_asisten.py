"""
server_asisten.py — Asisten PC Versi Chrome
============================================
Python berjalan sebagai WebSocket server di background.
Chrome membuka asisten.html sebagai "telinga" (Web Speech API).
Python menerima teks dari Chrome dan mengeksekusi perintah native Windows.

Perintah yang didukung:
  Buka [app]           → buka aplikasi
  Tutup [app]          → tutup/kill proses aplikasi
  Sembunyikan [app]    → minimize jendela app
  Sembunyikan semua    → minimize semua jendela (Win+D)
  Volume naik          → keraskan suara
  Volume turun         → pelankan suara
  Diamkan suara        → mute/unmute
  Mainkan              → play media
  Jeda                 → pause media
  Layar penuh          → toggle fullscreen (F11)
  Ketik [teks]         → ketik teks ke field aktif
"""

import asyncio
import ctypes
import json
import logging
import os
import subprocess
import threading
import time
import webbrowser
import websockets
import pygetwindow as gw
import pyperclip
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

# Matikan log bawaan HTTP server agar terminal bersih
logging.getLogger('http.server').setLevel(logging.ERROR)

# ── Konfigurasi ───────────────────────────────────────────────────────────────
HOST      = "localhost"
PORT      = 8765        # WebSocket
HTTP_PORT = 8766        # HTTP server (agar Chrome ingat izin mic)
HTML_DIR  = Path(__file__).parent
HTML_PATH = HTML_DIR / "asisten.html"

# ── Pemetaan App → Nama Proses (untuk tutup via taskkill) ────────────────────
PROCESS_MAP = {
    "whatsapp"    : "WhatsApp.exe",
    "notepad"     : "notepad.exe",
    "chrome"      : "chrome.exe",
    "spotify"     : "Spotify.exe",
    "explorer"    : "explorer.exe",
    "word"        : "WINWORD.EXE",
    "excel"       : "EXCEL.EXE",
    "powerpoint"  : "POWERPNT.EXE",
    "vscode"      : "Code.exe",
    "kalkulator"  : "CalculatorApp.exe",
    "calculator"  : "CalculatorApp.exe",
    "telegram"    : "Telegram.exe",
    "discord"     : "Discord.exe",
    "teams"       : "Teams.exe",
}

# ── Pemetaan Perintah Buka App ────────────────────────────────────────────────
# "cmd" = perintah shell langsung (andal untuk UWP & built-in Windows)
# "app" = nama untuk AppOpener (match_closest)
# "url" = buka URL di browser
APP_MAP = {
    "whatsapp"      : {"cmd": "start whatsapp:"},
    "notepad"       : {"cmd": "start notepad"},
    "kalkulator"    : {"cmd": "start calc"},
    "calculator"    : {"cmd": "start calc"},
    "chrome"        : {"app": "chrome"},
    "spotify"       : {"cmd": "start spotify:"},
    "vscode"        : {"app": "visual studio code"},
    "file explorer" : {"cmd": "start explorer"},
    "explorer"      : {"cmd": "start explorer"},
    "word"          : {"app": "microsoft word"},
    "excel"         : {"app": "microsoft excel"},
    "powerpoint"    : {"app": "microsoft powerpoint"},
    "telegram"      : {"app": "telegram"},
    "discord"       : {"app": "discord"},
    "youtube"       : {"url": "https://youtube.com"},
    "google"        : {"url": "https://google.com"},
    "instagram"     : {"url": "https://instagram.com"},
    "gmail"         : {"url": "https://mail.google.com"},
}

# ── Kata Pemicu ───────────────────────────────────────────────────────────────
BUKA_TRIGGERS       = ["buka", "open", "jalankan", "aktifkan", "launch"]
TUTUP_TRIGGERS      = ["tutup", "close", "keluar", "matikan"]
SEMBUNYI_TRIGGERS   = ["sembunyikan", "minimize", "kecilkan"]
KETIK_TRIGGERS      = ["ketik", "tulis", "type"]

# Perintah sistem tanpa target (dipetakan langsung)
SYSTEM_COMMANDS = {
    "volume naik"     : "volume_up",
    "keraskan suara"  : "volume_up",
    "keraskan"        : "volume_up",
    "volume turun"    : "volume_down",
    "pelankan suara"  : "volume_down",
    "pelankan"        : "volume_down",
    "diamkan suara"   : "mute",
    "diamkan"         : "mute",
    "mute"            : "mute",
    "mainkan"         : "play_pause",
    "play"            : "play_pause",
    "jeda"            : "play_pause",
    "pause"           : "play_pause",
    "layar penuh"     : "fullscreen",
    "fullscreen"      : "fullscreen",
    "sembunyikan semua" : "minimize_all",
    "kecilkan semua"  : "minimize_all",
    "minimize semua"  : "minimize_all",
}


# ══════════════════════════════════════════════════════════════════════════════
#  FUNGSI AKSI
# ══════════════════════════════════════════════════════════════════════════════

# ── Helper: tekan virtual key Windows ────────────────────────────────────────
def _press_vk(vk_code: int):
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP       = 0x0002
    ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_EXTENDEDKEY, 0)
    time.sleep(0.05)
    ctypes.windll.user32.keybd_event(vk_code, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)


# ── Buka ─────────────────────────────────────────────────────────────────────
def open_cmd(shell_cmd: str) -> str:
    try:
        subprocess.Popen(shell_cmd, shell=True)
        return f"OK (cmd): '{shell_cmd}'"
    except Exception as e:
        return f"GAGAL (cmd): {e}"


def open_app(app_name: str) -> str:
    try:
        import appopener
        appopener.open(app_name, match_closest=True, output=False)
        return f"OK: '{app_name}' dibuka."
    except Exception:
        try:
            subprocess.Popen(f'start "" "{app_name}"', shell=True)
            return f"OK (fallback): '{app_name}'"
        except Exception as e:
            return f"GAGAL: {e}"


def open_url(url: str) -> str:
    webbrowser.open(url)
    return f"OK: URL '{url}' dibuka."


# ── Tutup ─────────────────────────────────────────────────────────────────────
def close_app(name: str) -> str:
    name_lower = name.lower().strip()

    # Coba tutup via judul jendela
    try:
        matched = [w for w in gw.getAllWindows()
                   if name_lower in w.title.lower() and w.title.strip()]
        if matched:
            for w in matched:
                try:
                    w.close()
                except Exception:
                    pass
            return f"OK: '{name}' ditutup via window."
    except Exception:
        pass

    # Fallback: taskkill via nama proses
    proc = PROCESS_MAP.get(name_lower)
    if not proc:
        proc = f"{name}.exe"
    result = subprocess.run(
        f"taskkill /f /im {proc}",
        shell=True, capture_output=True, text=True
    )
    if result.returncode == 0:
        return f"OK: '{name}' ditutup via taskkill."
    return f"GAGAL tutup '{name}'. Proses tidak ditemukan."


# ── Sembunyikan / Minimize ────────────────────────────────────────────────────
def minimize_app(name: str) -> str:
    name_lower = name.lower().strip()
    try:
        matched = [w for w in gw.getAllWindows()
                   if name_lower in w.title.lower() and w.title.strip()]
        if matched:
            for w in matched:
                try:
                    w.minimize()
                except Exception:
                    pass
            return f"OK: '{name}' diminimize."
        return f"Tidak ditemukan jendela '{name}'."
    except Exception as e:
        return f"GAGAL minimize '{name}': {e}"


def minimize_all() -> str:
    # Win + D
    VK_LWIN = 0x5B
    VK_D    = 0x44
    ctypes.windll.user32.keybd_event(VK_LWIN, 0, 0, 0)
    ctypes.windll.user32.keybd_event(VK_D, 0, 0, 0)
    time.sleep(0.05)
    ctypes.windll.user32.keybd_event(VK_D, 0, 2, 0)
    ctypes.windll.user32.keybd_event(VK_LWIN, 0, 2, 0)
    return "OK: Semua jendela diminimize."


# ── Volume ────────────────────────────────────────────────────────────────────
def volume_up() -> str:
    # Tekan 5x VK_VOLUME_UP (~10% naik)
    for _ in range(5):
        _press_vk(0xAF)
        time.sleep(0.02)
    return "OK: Volume naik."


def volume_down() -> str:
    for _ in range(5):
        _press_vk(0xAE)
        time.sleep(0.02)
    return "OK: Volume turun."


def mute() -> str:
    _press_vk(0xAD)
    return "OK: Mute/unmute."


# ── Media ─────────────────────────────────────────────────────────────────────
def play_pause() -> str:
    _press_vk(0xB3)   # VK_MEDIA_PLAY_PAUSE
    return "OK: Play/Pause."


def fullscreen() -> str:
    _press_vk(0x7A)   # F11
    return "OK: Toggle fullscreen."


# ── Ketik Teks ────────────────────────────────────────────────────────────────
def type_text(text: str) -> str:
    try:
        pyperclip.copy(text)
        time.sleep(0.15)
        # Ctrl+V
        ctypes.windll.user32.keybd_event(0x11, 0, 0, 0)   # Ctrl down
        ctypes.windll.user32.keybd_event(0x56, 0, 0, 0)   # V down
        time.sleep(0.05)
        ctypes.windll.user32.keybd_event(0x56, 0, 2, 0)   # V up
        ctypes.windll.user32.keybd_event(0x11, 0, 2, 0)   # Ctrl up
        return f"OK: Teks '{text}' diketik."
    except Exception as e:
        return f"GAGAL ketik: {e}"


# ── Dispatch sistem ───────────────────────────────────────────────────────────
SYSTEM_DISPATCH = {
    "volume_up"   : volume_up,
    "volume_down" : volume_down,
    "mute"        : mute,
    "play_pause"  : play_pause,
    "fullscreen"  : fullscreen,
    "minimize_all": minimize_all,
}


# ══════════════════════════════════════════════════════════════════════════════
#  PARSER
# ══════════════════════════════════════════════════════════════════════════════
def parse_command(text: str):
    """
    Parse teks transkripsi menjadi aksi.
    Return dict dengan key 'action' + parameter lain, atau None jika diabaikan.
    """
    original = text.strip()
    text     = original.lower()

    # ── Perintah sistem tanpa target (cek dulu sebelum trigger) ──────────────
    for phrase, action in SYSTEM_COMMANDS.items():
        if phrase in text:
            return {"action": action}

    # ── "ketik [teks]" ────────────────────────────────────────────────────────
    for trigger in KETIK_TRIGGERS:
        if text.startswith(trigger + " "):
            content = original[len(trigger):].strip()
            return {"action": "type", "text": content}

    # ── "sembunyikan [app]" ───────────────────────────────────────────────────
    for trigger in SEMBUNYI_TRIGGERS:
        if text.startswith(trigger + " "):
            target = text[len(trigger):].strip()
            if any(k in target for k in ["semua", "all"]):
                return {"action": "minimize_all"}
            return {"action": "minimize", "target": target}

    # ── "tutup [app]" ─────────────────────────────────────────────────────────
    for trigger in TUTUP_TRIGGERS:
        if text.startswith(trigger + " "):
            target = text[len(trigger):].strip()
            return {"action": "close", "target": target}

    # ── "buka [app]" ──────────────────────────────────────────────────────────
    for trigger in BUKA_TRIGGERS:
        if text.startswith(trigger + " ") or text.startswith(trigger):
            target = text[len(trigger):].strip()
            if not target:
                return None

            # Cocokkan APP_MAP
            for keyword, app_action in APP_MAP.items():
                if keyword in target:
                    return {"action": "open", **app_action, "display": keyword}

            # Tidak ada di APP_MAP → coba AppOpener
            return {"action": "open", "app": target, "display": target}

    return None  # Tidak ada perintah yang cocok


# ══════════════════════════════════════════════════════════════════════════════
#  WEBSOCKET HANDLER
# ══════════════════════════════════════════════════════════════════════════════
async def handler(websocket):
    client_addr = websocket.remote_address
    print(f"[+] Client terhubung: {client_addr}")

    try:
        async for raw_msg in websocket:
            try:
                msg = json.loads(raw_msg)
            except json.JSONDecodeError:
                continue

            if msg.get("type") != "transcript":
                continue

            text = msg.get("text", "").strip()
            if not text:
                continue

            print(f"[Didengar] {text}")

            action = parse_command(text)
            if action is None:
                print(f"[~] Diabaikan: {text}")
                continue

            # ── Eksekusi berdasarkan action ───────────────────────────────────
            act = action.get("action")
            result       = "Aksi tidak dikenali."
            exec_display = act

            if act == "open":
                if "url" in action:
                    result       = open_url(action["url"])
                    exec_display = f"Buka URL: {action['display']}"
                elif "cmd" in action:
                    result       = open_cmd(action["cmd"])
                    exec_display = f"Buka: {action['display']}"
                else:
                    result       = open_app(action["app"])
                    exec_display = f"Buka aplikasi: {action['display']}"

            elif act == "close":
                result       = close_app(action["target"])
                exec_display = f"Tutup: {action['target']}"

            elif act == "minimize":
                result       = minimize_app(action["target"])
                exec_display = f"Sembunyikan: {action['target']}"

            elif act == "type":
                result       = type_text(action["text"])
                exec_display = f"Ketik: \"{action['text']}\""

            elif act in SYSTEM_DISPATCH:
                result       = SYSTEM_DISPATCH[act]()
                exec_display = act.replace("_", " ").capitalize()

            print(f"[Eksekusi] {result}")

            await websocket.send(json.dumps({
                "type"   : "exec",
                "command": exec_display,
                "result" : result
            }))

    except websockets.exceptions.ConnectionClosedOK:
        print(f"[-] Client terputus (normal): {client_addr}")
    except websockets.exceptions.ConnectionClosedError as e:
        print(f"[-] Client terputus (error): {client_addr} — {e}")


# ══════════════════════════════════════════════════════════════════════════════
#  HTTP SERVER (agar Chrome menyimpan izin mic)
# ══════════════════════════════════════════════════════════════════════════════
class SilentHTTPHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # diam — tidak perlu log HTTP di terminal

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(HTML_DIR), **kwargs)


def start_http_server():
    server = HTTPServer((HOST, HTTP_PORT), SilentHTTPHandler)
    print(f"[HTTP] Server aktif di http://{HOST}:{HTTP_PORT}")
    server.serve_forever()


# ══════════════════════════════════════════════════════════════════════════════
#  LAUNCH BROWSER
# ══════════════════════════════════════════════════════════════════════════════
def launch_browser():
    """Buka asisten.html via http://localhost agar Chrome menyimpan izin mic."""
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
            "--window-size=540,560",
            "--window-position=40,40",
        ])
        print(f"[Browser] Chrome dibuka: {url}")
    else:
        webbrowser.open(url)
        print(f"[Browser] Browser default dibuka: {url}")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════
async def main():
    print("=" * 54)
    print("  Asisten PC — Server WebSocket Aktif")
    print(f"  WS  : ws://{HOST}:{PORT}")
    print(f"  HTTP: http://{HOST}:{HTTP_PORT}")
    print("  Tekan Ctrl+C untuk berhenti.")
    print("=" * 54)

    # HTTP server di thread terpisah (daemon)
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
