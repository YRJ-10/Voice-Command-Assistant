import customtkinter as ctk
import threading
import pyaudio
import audioop
import speech_recognition as sr
from AppOpener import open as open_app
import time

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class AsistenGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Asisten PC - Voice Command")
        self.geometry("550x450")
        self.resizable(False, False)
        
        # Variabel State
        self.is_listening = False
        self.audio_thread = None
        
        # --- UI Elements ---
        self.lbl_title = ctk.CTkLabel(self, text="ASISTEN PRIBADI PC", font=("Roboto", 22, "bold"))
        self.lbl_title.pack(pady=(20, 5))
        
        self.lbl_status = ctk.CTkLabel(self, text="Status: Siap (Menunggu)", font=("Roboto", 14), text_color="gray")
        self.lbl_status.pack(pady=5)
        
        # Progress Bar untuk Indikator Volume Mic
        self.lbl_vol = ctk.CTkLabel(self, text="Indikator Volume Mic:", font=("Roboto", 12))
        self.lbl_vol.pack(anchor="w", padx=50)
        
        self.progressbar = ctk.CTkProgressBar(self, width=450, height=15)
        self.progressbar.pack(pady=(0, 15))
        self.progressbar.set(0)
        
        # Log Box
        self.textbox = ctk.CTkTextbox(self, width=450, height=180, font=("Consolas", 13))
        self.textbox.pack(pady=5)
        self.textbox.insert("0.0", "--- Monitor Log Aktif ---\n")
        self.textbox.configure(state="disabled")
        
        # Tombol Aksi
        self.btn_toggle = ctk.CTkButton(self, text="▶ Mulai Mendengarkan", command=self.toggle_listening, height=40, font=("Roboto", 14, "bold"))
        self.btn_toggle.pack(pady=15)
        
    def log(self, text):
        # Update teks secara aman dari thread lain
        self.after(0, self._append_log, text)
        
    def _append_log(self, text):
        self.textbox.configure(state="normal")
        self.textbox.insert("end", text + "\n")
        self.textbox.see("end")
        self.textbox.configure(state="disabled")

    def toggle_listening(self):
        if not self.is_listening:
            self.is_listening = True
            self.btn_toggle.configure(text="■ Berhenti", fg_color="#C62828", hover_color="#B71C1C")
            self.lbl_status.configure(text="Status: Mendengarkan...", text_color="#4CAF50")
            
            # Jalankan loop mic di background agar GUI tidak freeze
            self.audio_thread = threading.Thread(target=self.listen_loop, daemon=True)
            self.audio_thread.start()
        else:
            self.is_listening = False
            self.btn_toggle.configure(text="▶ Mulai Mendengarkan", fg_color=["#3B8ED0", "#1F6AA5"])
            self.lbl_status.configure(text="Status: Dihentikan", text_color="gray")
            self.progressbar.set(0)
            
    def process_command(self, text_command):
        if text_command.startswith("buka"):
            app_name = text_command.replace("buka", "").strip()
            if app_name:
                self.log(f"[Sistem] Mengeksekusi: Buka aplikasi '{app_name}'...")
                # Eksekusi membuka aplikasi
                threading.Thread(target=open_app, args=(app_name,), kwargs={"match_closest": True}, daemon=True).start()
            else:
                self.log("[Sistem] Gagal: Nama aplikasi tidak disebutkan.")
        else:
            self.log("[Sistem] Gagal: Perintah tidak diawali kata 'Buka'.")

    def listen_loop(self):
        from collections import deque
        
        CHUNK = 1024
        FORMAT = pyaudio.paInt16
        CHANNELS = 1
        RATE = 16000
        
        p = pyaudio.PyAudio()
        try:
            stream = p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
        except Exception as e:
            self.log(f"[Error] Tidak dapat mengakses mikrofon: {e}")
            self.after(0, self.toggle_listening)
            return
            
        recognizer = sr.Recognizer()
        
        # --- KALIBRASI KEBISINGAN KABEL / RUANGAN ---
        self.log("[Sistem] Mengkalibrasi noise kabel/ruangan... (Harap diam 1 detik)")
        self.after(0, self.lbl_status.configure, {"text": "Status: Kalibrasi...", "text_color": "yellow"})
        
        noise_samples = []
        for _ in range(0, int(RATE / CHUNK * 1.5)): # 1.5 detik
            data = stream.read(CHUNK, exception_on_overflow=False)
            noise_samples.append(audioop.rms(data, 2))
            
        avg_noise = sum(noise_samples) / len(noise_samples)
        THRESHOLD = avg_noise * 1.5 + 800  # Buat batas di atas noise kabel
        self.log(f"[Info] Ambang batas (Threshold) disetel ke: {THRESHOLD:.0f}")
        # ---------------------------------------------
        
        SILENCE_LIMIT = 20 # 20 chunk ~ 1.2 detik diam sebelum mengakhiri 1 kalimat
        pre_speech_buffer = deque(maxlen=10) # Menyimpan memori suara 0.6 detik sebelumnya agar awal kata tidak terpotong
        
        frames = []
        is_speaking = False
        silence_count = 0
        
        self.log("[Sistem] Mikrofon terhubung. Filter Noise Aktif. Silakan bicara.")
        self.after(0, self.lbl_status.configure, {"text": "Status: Mendengarkan...", "text_color": "#4CAF50"})
        
        while self.is_listening:
            try:
                data = stream.read(CHUNK, exception_on_overflow=False)
                rms = audioop.rms(data, 2)
                
                # Animasikan progress bar (Vol: 0 hingga 3x lipat threshold)
                vol_ratio = min(1.0, rms / (THRESHOLD * 3))
                self.after(0, self.progressbar.set, vol_ratio)
                
                if rms > THRESHOLD:
                    if not is_speaking:
                        is_speaking = True
                        self.after(0, self.lbl_status.configure, {"text": "Status: Merekam Suara...", "text_color": "#FF9800"})
                        frames = list(pre_speech_buffer) # Jahit memori awal kata
                    frames.append(data)
                    silence_count = 0
                elif is_speaking:
                    frames.append(data)
                    silence_count += 1
                    if silence_count > SILENCE_LIMIT:
                        # Selesai bicara
                        is_speaking = False
                        self.after(0, self.lbl_status.configure, {"text": "Status: Menerjemahkan (Google API)...", "text_color": "#2196F3"})
                        self.after(0, self.progressbar.set, 0)
                        
                        audio_data = sr.AudioData(b"".join(frames), RATE, p.get_sample_size(FORMAT))
                        
                        try:
                            # Kirim ke google
                            text = recognizer.recognize_google(audio_data, language="id-ID").lower()
                            self.log(f"[Anda] {text}")
                            self.process_command(text)
                        except sr.UnknownValueError:
                            self.log("[Sistem] Suara terpotong/tidak jelas. Coba lagi.")
                        except sr.RequestError as e:
                            self.log(f"[Sistem] Error Koneksi Internet: {e}")
                            
                        if self.is_listening:
                            self.after(0, self.lbl_status.configure, {"text": "Status: Mendengarkan...", "text_color": "#4CAF50"})
                        
                        frames = []
                        silence_count = 0
                        pre_speech_buffer.clear()
                else:
                    # Selalu simpan suara diam ke buffer memori
                    pre_speech_buffer.append(data)
                        
            except Exception as e:
                self.log(f"[Error] Membaca stream audio: {e}")
                break
                
        stream.stop_stream()
        stream.close()
        p.terminate()

if __name__ == "__main__":
    app = AsistenGUI()
    app.mainloop()
