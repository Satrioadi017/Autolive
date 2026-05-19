"""
generate_assets.py
Jalankan sekali untuk membuat semua aset yang dibutuhkan bot YouTube Live.
Kebutuhan: pip install Pillow numpy
"""

import os
import math
import random
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1280, 720
ASSETS = os.path.join(os.path.dirname(__file__), "assets")

def mkdir(path):
    os.makedirs(path, exist_ok=True)

# ─────────────────────────────────────────────
# BACKGROUNDS
# ─────────────────────────────────────────────

def bg_gradient_lofi(path):
    """Gradient ungu-biru lofi gelap."""
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    top, bot = (30, 20, 60), (10, 60, 90)
    for y in range(H):
        t = y / H
        r = int(top[0] + (bot[0]-top[0])*t)
        g = int(top[1] + (bot[1]-top[1])*t)
        b = int(top[2] + (bot[2]-top[2])*t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    # Noise grain
    arr = np.array(img).astype(np.int16)
    noise = np.random.randint(-12, 12, arr.shape, dtype=np.int16)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    img.save(path)
    print(f"  [OK] {path}")

def bg_gradient_warm(path):
    """Gradient oranye-merah hangat sunset."""
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    top, bot = (80, 20, 40), (160, 60, 20)
    for y in range(H):
        t = y / H
        r = int(top[0] + (bot[0]-top[0])*t)
        g = int(top[1] + (bot[1]-top[1])*t)
        b = int(top[2] + (bot[2]-top[2])*t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    arr = np.array(img).astype(np.int16)
    noise = np.random.randint(-10, 10, arr.shape, dtype=np.int16)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    img.save(path)
    print(f"  [OK] {path}")

def bg_gradient_forest(path):
    """Gradient hijau gelap — cocok untuk study/chill."""
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    top, bot = (10, 40, 30), (5, 70, 50)
    for y in range(H):
        t = y / H
        r = int(top[0] + (bot[0]-top[0])*t)
        g = int(top[1] + (bot[1]-top[1])*t)
        b = int(top[2] + (bot[2]-top[2])*t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    arr = np.array(img).astype(np.int16)
    noise = np.random.randint(-8, 8, arr.shape, dtype=np.int16)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr)
    img.save(path)
    print(f"  [OK] {path}")

def bg_gradient_midnight(path):
    """Deep midnight blue — cocok untuk konten malam."""
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)
    top, bot = (5, 5, 30), (15, 15, 60)
    for y in range(H):
        t = y / H
        r = int(top[0] + (bot[0]-top[0])*t)
        g = int(top[1] + (bot[1]-top[1])*t)
        b = int(top[2] + (bot[2]-top[2])*t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    # Bintang-bintang
    arr = np.array(img)
    rng = random.Random(42)
    for _ in range(200):
        x = rng.randint(0, W-1)
        y = rng.randint(0, H//2)
        brightness = rng.randint(120, 255)
        size = rng.randint(1, 2)
        for dy in range(-size, size+1):
            for dx in range(-size, size+1):
                nx, ny = x+dx, y+dy
                if 0 <= nx < W and 0 <= ny < H:
                    arr[ny, nx] = [brightness, brightness, brightness]
    img = Image.fromarray(arr)
    img.save(path)
    print(f"  [OK] {path}")

def bg_geometric_grid(path):
    """Grid geometrik — modern & clean."""
    img = Image.new("RGB", (W, H), (18, 18, 28))
    draw = ImageDraw.Draw(img)
    # Grid lines
    for x in range(0, W, 80):
        draw.line([(x, 0), (x, H)], fill=(40, 40, 60), width=1)
    for y in range(0, H, 80):
        draw.line([(0, y), (W, y)], fill=(40, 40, 60), width=1)
    # Titik-titik di perpotongan grid
    for x in range(0, W, 80):
        for y in range(0, H, 80):
            draw.ellipse([(x-2, y-2), (x+2, y+2)], fill=(80, 80, 120))
    img.save(path)
    print(f"  [OK] {path}")

def bg_circle_bokeh(path):
    """Bokeh circles — aesthetic blur."""
    img = Image.new("RGB", (W, H), (20, 15, 35))
    draw = ImageDraw.Draw(img)
    rng = random.Random(7)
    colors = [
        (100, 60, 150, 60), (60, 100, 180, 50),
        (180, 80, 100, 40), (80, 160, 130, 45),
        (200, 140, 60, 35),
    ]
    for _ in range(30):
        cx = rng.randint(0, W)
        cy = rng.randint(0, H)
        r  = rng.randint(40, 180)
        col = rng.choice(colors)
        draw.ellipse([(cx-r, cy-r), (cx+r, cy+r)], fill=col[:3])
    img = img.filter(ImageFilter.GaussianBlur(radius=40))
    img.save(path)
    print(f"  [OK] {path}")

# ─────────────────────────────────────────────
# OVERLAYS
# ─────────────────────────────────────────────

def overlay_vignette(path):
    """Efek vignette gelap di tepi layar — RGBA."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    arr = np.zeros((H, W, 4), dtype=np.uint8)
    cx, cy = W/2, H/2
    for y in range(H):
        for x in range(W):
            dx = (x - cx) / cx
            dy = (y - cy) / cy
            dist = math.sqrt(dx*dx + dy*dy)
            alpha = int(min(255, max(0, (dist - 0.5) * 340)))
            arr[y, x] = [0, 0, 0, alpha]
    img = Image.fromarray(arr, "RGBA")
    img.save(path)
    print(f"  [OK] {path}")

def overlay_scanlines(path):
    """Efek scanline retro CRT — RGBA."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    for y in range(0, H, 3):
        draw.line([(0, y), (W, y)], fill=(0, 0, 0, 30))
    img.save(path)
    print(f"  [OK] {path}")

def overlay_top_bar(path):
    """Bar semi-transparan di atas untuk header channel."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Header bar atas
    draw.rectangle([(0, 0), (W, 70)], fill=(0, 0, 0, 160))
    # Garis pemisah bawah header
    draw.line([(0, 70), (W, 70)], fill=(255, 255, 255, 60), width=1)
    # Footer bar bawah
    draw.rectangle([(0, H-60), (W, H)], fill=(0, 0, 0, 160))
    draw.line([(0, H-60), (W, H-60)], fill=(255, 255, 255, 60), width=1)
    img.save(path)
    print(f"  [OK] {path}")

def overlay_live_badge(path):
    """Badge LIVE merah — RGBA, bisa ditempel di pojok."""
    size = (120, 44)
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([(0, 0), (size[0]-1, size[1]-1)],
                            radius=8, fill=(220, 30, 30, 230))
    # Titik putih
    draw.ellipse([(10, 16), (22, 28)], fill=(255, 255, 255, 255))
    img.save(path)
    print(f"  [OK] {path}")

def overlay_corner_decoration(path):
    """Dekorasi sudut geometris — RGBA."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    col = (255, 255, 255, 50)
    L = 60
    # Sudut kiri atas
    draw.line([(20, 20), (20+L, 20)], fill=col, width=2)
    draw.line([(20, 20), (20, 20+L)], fill=col, width=2)
    # Sudut kanan atas
    draw.line([(W-20, 20), (W-20-L, 20)], fill=col, width=2)
    draw.line([(W-20, 20), (W-20, 20+L)], fill=col, width=2)
    # Sudut kiri bawah
    draw.line([(20, H-20), (20+L, H-20)], fill=col, width=2)
    draw.line([(20, H-20), (20, H-20-L)], fill=col, width=2)
    # Sudut kanan bawah
    draw.line([(W-20, H-20), (W-20-L, H-20)], fill=col, width=2)
    draw.line([(W-20, H-20), (W-20, H-20-L)], fill=col, width=2)
    img.save(path)
    print(f"  [OK] {path}")

# ─────────────────────────────────────────────
# PLACEHOLDER FONT INFO
# ─────────────────────────────────────────────

def write_font_readme(path):
    content = """# FONTS — Download Gratis

Simpan file .ttf ke folder ini (assets/fonts/).

## REKOMENDASI FONT (Semua GRATIS & Open Source):

### 1. Untuk Teks Utama (Quote / Konten)
- **Nunito** → https://fonts.google.com/specimen/Nunito
- **Poppins** → https://fonts.google.com/specimen/Poppins

### 2. Untuk Header / Judul
- **Righteous** → https://fonts.google.com/specimen/Righteous
- **Montserrat** → https://fonts.google.com/specimen/Montserrat

### 3. Untuk Lo-Fi / Aesthetic
- **Space Mono** → https://fonts.google.com/specimen/Space+Mono
- **VT323** (pixel retro) → https://fonts.google.com/specimen/VT323

## CARA DOWNLOAD MASSAL (Semua Sekaligus):
1. Buka https://fonts.google.com
2. Pilih font yang diinginkan → klik ikon + 
3. Klik "Download all" di pojok kanan bawah
4. Extract .ttf ke folder ini

## Rename file setelah download agar mudah dipakai di kode:
  NunitoRegular.ttf
  NunitoBold.ttf
  PoppinsRegular.ttf
  PoppinsBold.ttf
  Righteous.ttf
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  [OK] {path}")

# ─────────────────────────────────────────────
# PLACEHOLDER MUSIC INFO
# ─────────────────────────────────────────────

def write_music_readme(path):
    content = """# MUSIC — Sumber Musik Bebas Royalti

Simpan file .mp3 ke folder ini (assets/music/).

## SUMBER MUSIK GRATIS TERPERCAYA:

### 1. Pixabay Music (TERBAIK — tidak perlu credit)
   https://pixabay.com/music/
   → Search: "lofi", "chill", "study", "meditation"
   → Download langsung, gratis, no credit required

### 2. YouTube Audio Library
   https://studio.youtube.com → Audio Library
   → Filter: Genre "Lo-fi" atau "Ambient"
   → Cocok khusus untuk konten YouTube

### 3. Free Music Archive
   https://freemusicarchive.org
   → Filter lisensi CC0 atau CC BY

### 4. Chillhop Music (Lo-fi khusus)
   https://chillhop.com/free-music-for-content-creators/
   → Perlu credit di deskripsi video

## REKOMENDASI SEARCH TERM:
  "lofi hip hop instrumental"
  "chill study music no copyright"
  "ambient meditation music free"
  "lofi beats royalty free"

## NAMA FILE YANG DISARANKAN (agar kode bisa loop random):
  music_lofi_01.mp3
  music_lofi_02.mp3
  music_chill_01.mp3
  music_ambient_01.mp3
  music_meditation_01.mp3

## MINIMAL: Simpan 3-5 file .mp3 agar bot bisa shuffle acak.
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  [OK] {path}")

# ─────────────────────────────────────────────
# FALLBACK CONTENT
# ─────────────────────────────────────────────

def write_fallback_content(path):
    import json
    content = {
        "MOTIVATIONAL_QUOTES": [
            "Mulailah dari mana kamu berada, gunakan apa yang kamu punya.",
            "Setiap hari adalah kesempatan baru untuk jadi lebih baik.",
            "Jangan tunggu sempurna, mulai dulu.",
            "Kesuksesan adalah hasil dari kebiasaan kecil yang dilakukan setiap hari.",
            "Kamu tidak perlu luar biasa untuk memulai, tapi kamu harus memulai untuk menjadi luar biasa.",
            "Satu langkah kecil hari ini lebih baik dari rencana besar yang tidak pernah dimulai.",
            "Percayalah pada prosesnya, hasilnya akan mengikuti.",
            "Keberanian bukan berarti tidak takut, tapi tetap melangkah meski takut.",
            "Mimpi tanpa aksi hanyalah khayalan. Aksi tanpa mimpi hanyalah rutinitas.",
            "Jadilah versi terbaik dirimu, bukan salinan terbaik orang lain."
        ],
        "TRIVIA_QNA": [
            "Negara mana yang memiliki pulau terbanyak di dunia? Jawaban: Swedia (sekitar 221.800 pulau)!",
            "Berapa persen otak manusia yang terdiri dari air? Jawaban: sekitar 73 persen!",
            "Hewan apa yang tidak pernah tidur? Jawaban: Bullfrog — mereka selalu waspada!",
            "Planet mana yang berputar berlawanan arah dibanding planet lainnya? Jawaban: Venus!",
            "Siapa penemu bola lampu? Jawaban: Thomas Edison (1879).",
            "Bahasa apa yang paling banyak digunakan di dunia? Jawaban: Mandarin (bahasa ibu)!",
            "Berapa jumlah tulang pada tubuh manusia dewasa? Jawaban: 206 tulang.",
            "Apa nama ibu kota Australia? Jawaban: Canberra, bukan Sydney!",
            "Berapa lama lebah ratu bisa hidup? Jawaban: 3 sampai 5 tahun.",
            "Negara mana yang pertama kali memberikan hak pilih kepada perempuan? Jawaban: Selandia Baru (1893)."
        ],
        "STUDY_WITH_ME": [
            "Sesi fokus 25 menit dimulai! Matikan notifikasi HP kamu. Kamu bisa!",
            "Pomodoro #1 — Ambil napas, fokus pada satu tugas, dan mulai sekarang.",
            "Ingat: belajar bukan soal berapa lama, tapi seberapa fokus kamu.",
            "Istirahat 5 menit! Regangkan badan, minum air, lanjut lagi.",
            "Sesi baru dimulai. Tulis 3 hal yang ingin kamu selesaikan hari ini.",
            "Deep work mode: jauhkan HP, buka hanya tab yang perlu. Gas!",
            "Kamu sudah sampai sejauh ini — terus lanjutkan, jangan berhenti sekarang.",
            "Teknik Feynman: coba jelaskan materi yang baru kamu pelajari dengan kata-katamu sendiri.",
            "Istirahat panjang 15 menit. Jalan sebentar, udara segar membantu konsentrasi.",
            "Final sprint! Selesaikan satu tugas terakhir sebelum istirahat berikutnya."
        ],
        "MEDITATION_GUIDE": [
            "Tutup mata, tarik napas dalam 4 hitungan, tahan 4 hitungan, hembuskan 6 hitungan.",
            "Rasakan beban hari ini perlahan-lahan lepas seiring setiap hembusan napas.",
            "Fokus hanya pada suara di sekitarmu. Biarkan pikiran datang dan pergi tanpa dipegang.",
            "Rilekskan bahu, lepaskan ketegangan di rahang. Kamu aman di sini.",
            "Bayangkan cahaya hangat mengalir dari ujung kepala hingga ujung kaki.",
            "Satu hal yang kamu syukuri hari ini — pikirkan, rasakan, dan tersenyumlah.",
            "Setiap momen ini adalah hadiah. Hadir sepenuhnya, tanpa khawatir masa depan.",
            "Tubuhmu sudah bekerja keras hari ini. Berikan ia istirahat yang layak.",
            "Biarkan pikiran mengembara sebentar, lalu perlahan bawa kembali ke napasmu.",
            "Malam yang tenang untuk jiwa yang tenang. Kamu sudah melakukan yang terbaik hari ini."
        ],
        "LOFI_FACTS": [
            "Musik lo-fi hip hop pertama kali populer di YouTube sekitar tahun 2015 sebagai musik belajar.",
            "Otak manusia memproses musik secara bersamaan di banyak area berbeda — itulah kenapa musik bisa mengubah suasana hati.",
            "Mendengarkan musik dengan BPM 60-70 terbukti membantu otak masuk ke kondisi alfa — ideal untuk belajar.",
            "Efek suara hujan dalam lo-fi disebut 'pink noise' — membantu menyamarkan gangguan sekitar.",
            "Kata 'lo-fi' adalah kependekan dari 'low fidelity' — rekaman dengan kualitas sedikit imperfect secara sengaja.",
            "Studi menunjukkan musik instrumental tanpa lirik lebih efektif untuk fokus belajar.",
            "Kopi adalah minuman kedua paling banyak dikonsumsi di dunia setelah air — cocok untuk sesi lo-fi!",
            "Tumbuhan bereaksi terhadap musik — beberapa penelitian menunjukkan mereka tumbuh lebih baik dengan musik lembut.",
            "Rata-rata manusia memiliki 60.000 hingga 80.000 pikiran per hari.",
            "Otak kita tidak pernah benar-benar berhenti bekerja — bahkan saat tidur, ia memproses memori."
        ]
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(content, f, ensure_ascii=False, indent=2)
    print(f"  [OK] {path}")

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    print("=" * 55)
    print("  AUTOLIVE ASSET GENERATOR")
    print("=" * 55)

    # Buat semua folder
    dirs = [
        os.path.join(ASSETS, "backgrounds"),
        os.path.join(ASSETS, "overlays"),
        os.path.join(ASSETS, "fonts"),
        os.path.join(ASSETS, "music"),
    ]
    for d in dirs:
        mkdir(d)

    # BACKGROUNDS
    print("\n[1/4] Membuat backgrounds...")
    bg_gradient_lofi   (os.path.join(ASSETS, "backgrounds", "lofi_purple.png"))
    bg_gradient_warm   (os.path.join(ASSETS, "backgrounds", "warm_sunset.png"))
    bg_gradient_forest (os.path.join(ASSETS, "backgrounds", "forest_green.png"))
    bg_gradient_midnight(os.path.join(ASSETS, "backgrounds", "midnight_stars.png"))
    bg_geometric_grid  (os.path.join(ASSETS, "backgrounds", "geometric_grid.png"))
    bg_circle_bokeh    (os.path.join(ASSETS, "backgrounds", "bokeh_circles.png"))

    # OVERLAYS
    print("\n[2/4] Membuat overlays...")
    overlay_vignette          (os.path.join(ASSETS, "overlays", "vignette.png"))
    overlay_scanlines         (os.path.join(ASSETS, "overlays", "scanlines.png"))
    overlay_top_bar           (os.path.join(ASSETS, "overlays", "top_bottom_bar.png"))
    overlay_live_badge        (os.path.join(ASSETS, "overlays", "live_badge.png"))
    overlay_corner_decoration (os.path.join(ASSETS, "overlays", "corner_deco.png"))

    # FONTS (README)
    print("\n[3/4] Membuat panduan font...")
    write_font_readme(os.path.join(ASSETS, "fonts", "README.txt"))

    # MUSIC (README)
    print("\n[4/4] Membuat panduan musik...")
    write_music_readme(os.path.join(ASSETS, "music", "README.txt"))

    # FALLBACK CONTENT
    print("\n[+] Membuat fallback_content.json...")
    write_fallback_content(os.path.join(ASSETS, "fallback_content.json"))

    print("\n" + "=" * 55)
    print("  SELESAI! Struktur folder yang dibuat:")
    print("=" * 55)
    for root, dirs_list, files in os.walk(ASSETS):
        level = root.replace(ASSETS, "").count(os.sep)
        indent = "  " * level
        print(f"{indent}📁 {os.path.basename(root)}/")
        subindent = "  " * (level + 1)
        for f in files:
            size = os.path.getsize(os.path.join(root, f))
            print(f"{subindent}📄 {f}  ({size//1024} KB)")

    print("\n⚠️  PERLU DILAKUKAN MANUAL:")
    print("  - Download font .ttf → lihat assets/fonts/README.txt")
    print("  - Download musik .mp3 → lihat assets/music/README.txt")
    print("\n✅ Semua aset siap. Jalankan: python main.py --dry-run")

if __name__ == "__main__":
    main()
