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
import webbrowser
import websockets
from pathlib import Path

# ── Konfigurasi ───────────────────────────────────────────────────────────────
HOST = "localhost"
PORT = 8765
HTML_PATH = Path(__file__).parent / "asisten.html"

# ── Pemetaan perintah ke aplikasi ─────────────────────────────────────────────
# Kunci: kata kunci dalam ucapan (lowercase)
# Nilai: nama aplikasi untuk AppOpener, atau perintah langsung
APP_MAP = {
    "whatsapp"    : {"app": "whatsapp"},
    "notepad"     : {"app": "notepad"},
    "kalkulator"  : {"app": "calculator"},
    "calculator"  : {"app": "calculator"},
    "chrome"      : {"app": "chrome"},
    "spotify"     : {"app": "spotify"},
    "vscode"      : {"app": "visual studio code"},
    "file explorer": {"app": "explorer"},
    "explorer"    : {"app": "explorer"},
    "word"        : {"app": "microsoft word"},
    "excel"       : {"app": "microsoft excel"},
    "powerpoint"  : {"app": "microsoft powerpoint"},
    "youtube"     : {"url": "https://youtube.com"},
    "google"      : {"url": "https://google.com"},
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


def open_app(app_name: str) -> str:
    """Buka aplikasi menggunakan AppOpener."""
    try:
        import appopener
        appopener.open(app_name, match_closest=True, output=False)
        return f"OK: '{app_name}' dibuka."
    except Exception as e:
        # Fallback: coba via subprocess start
        try:
            subprocess.Popen(["cmd", "/c", "start", app_name], shell=False)
            return f"OK (fallback): '{app_name}' dibuka."
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


# ── Buka Chrome ke asisten.html ───────────────────────────────────────────────
def launch_browser():
    """
    Buka asisten.html di Chrome dengan tampilan minimalis (--app mode).
    Jika Chrome tidak ditemukan, gunakan browser default.
    """
    html_uri = HTML_PATH.as_uri()

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
            f"--app={html_uri}",
            "--window-size=540,520",
            "--window-position=40,40",
        ])
        print(f"[Browser] Chrome dibuka: {html_uri}")
    else:
        webbrowser.open(html_uri)
        print(f"[Browser] Browser default dibuka: {html_uri}")


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    print("=" * 52)
    print("  Asisten PC — Server WebSocket Aktif")
    print(f"  Listening di ws://{HOST}:{PORT}")
    print("  Tekan Ctrl+C untuk berhenti.")
    print("=" * 52)

    # Buka browser setelah server siap
    loop = asyncio.get_event_loop()
    loop.call_later(1.0, launch_browser)

    async with websockets.serve(handler, HOST, PORT):
        await asyncio.Future()  # jalan selamanya


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Server] Dihentikan oleh user.")
