import speech_recognition as sr
from AppOpener import open as open_app
import sys

def main():
    # 1. Inisialisasi recognizer dan microphone
    recognizer = sr.Recognizer()
    try:
        mic = sr.Microphone()
    except OSError as e:
        print(f"Error accessing microphone: {e}")
        print("Pastikan mikrofon tersambung dan diizinkan.")
        sys.exit(1)

    # Menampilkan daftar mikrofon untuk debugging jika diperlukan
    # print("Daftar Mikrofon:", sr.Microphone.list_microphone_names())

    # 2. Mendengarkan suara
    with mic as source:
        print("\n--- ASISTEN PC AKTIF ---")
        print("Mendengarkan kebisingan ruangan... (Harap diam 1 detik)")
        # Menyesuaikan dengan noise ruangan (ambient noise) agar lebih akurat
        recognizer.adjust_for_ambient_noise(source, duration=1)
        # Menurunkan ambang batas suara secara manual jika ruangan terlalu sepi dan mic kurang sensitif
        if recognizer.energy_threshold > 3000:
            recognizer.energy_threshold = 3000
        print(f"[Info] Sensitivitas mic diatur ke: {recognizer.energy_threshold:.0f}")
        
        print("\nSilakan ucapkan perintah Anda (contoh: 'Buka Notepad')")
        print("Mulai bicara sekarang...")
        
        try:
            # timeout ditingkatkan menjadi None agar terus mendengarkan sampai ada suara,
            # dan phrase_time_limit ditambahkan agar tidak merekam terlalu lama
            audio = recognizer.listen(source, timeout=None, phrase_time_limit=10)
        except sr.WaitTimeoutError:
            print("Waktu habis. Tidak ada suara terdeteksi.")
            sys.exit(0)

    # 3. Menerjemahkan menggunakan Google Speech API (Bahasa Indonesia)
    try:
        print("Menerjemahkan suara...")
        text_command = recognizer.recognize_google(audio, language="id-ID").lower()
        print(f"\n[!] Suara terdeteksi: '{text_command}'")
        
        # 4. Memproses perintah "buka + [nama aplikasi]"
        if text_command.startswith("buka"):
            # Mengambil nama aplikasi setelah kata "buka "
            app_name = text_command.replace("buka", "").strip()
            if app_name:
                print(f"[>] Menjalankan perintah: Membuka aplikasi '{app_name}'...")
                # Membuka aplikasi terdekat namanya
                open_app(app_name, match_closest=True)
            else:
                print("Nama aplikasi tidak disebutkan. Contoh yang benar: 'Buka Chrome'")
        else:
            print("Perintah tidak dikenali. Pastikan Anda memulai dengan kata 'Buka'.")

    except sr.UnknownValueError:
        print("Maaf, suara kurang jelas atau tidak bisa dipahami. Silakan coba lagi.")
    except sr.RequestError as e:
        print(f"Gagal menghubungkan ke layanan Google Speech Recognition. Periksa internet Anda. Error: {e}")
    except Exception as e:
        print(f"Terjadi kesalahan tidak terduga: {e}")

if __name__ == "__main__":
    main()
