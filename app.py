from flask import Flask, render_template, request, jsonify
app = Flask(__name__)

@app.route('/')
def home():
    return '<h1>Goaltech Chess Calisiyor!</h1>'


import jwt
import time
import math
import sqlite3

# =====================================================================
# 1. RENKLER VE OYUN VERİLERİ
# =====================================================================
ACIK_KARE = (235, 236, 208)
KOYU_KARE = (65, 75, 86)
BEYAZ_TAS_RENK = (255, 255, 255)    # Saf Beyaz
SIYAH_TAS_RENK = (0, 0, 0)          # Saf Siyah
ARKAPLAN_RENK = (18, 22, 28)
PANEL_RENK = (30, 36, 46)
KUTU_RENK = (20, 25, 32)
SARI_SECIM = (245, 245, 100)
YESIL_NOKTA = (50, 205, 50)
SAH_TEHDIT_RENK = (220, 60, 60)     # Şah çekildiğinde karenin kızarması için
BEYAZ = (255, 255, 255)
GRI = (140, 150, 165)
UYARI_RENK = (255, 75, 75)

SEMBOLLER = {
    'K': '♔', 'Q': '♕', 'R': '♖', 'B': '♗', 'N': '♘', 'P': '♙',
    'k': '♚', 'q': '♛', 'r': '♜', 'b': '♝', 'n': '♞', 'p': '♟',
    ' ': ' '
}

TAS_PUANLARI = {'P': 1, 'N': 3, 'B': 3, 'R': 5, 'Q': 9, 'K': 0}
TAS_ISIMLERI = {'P': 'Piyon', 'N': 'At', 'B': 'Fil', 'R': 'Kale', 'Q': 'Vezir', 'K': 'Şah'}

# Rok ve En Passant (Geçerken alma) durum takipleri
beyaz_sah_oynadi = False
beyaz_kale_sol_oynadi = False
beyaz_kale_sag_oynadi = False
siyah_sah_oynadi = False
siyah_kale_sol_oynadi = False
siyah_kale_sag_oynadi = False

gecerken_alinabilir_kare = None
elli_hamle_sayaci = 0
konum_gecmisi = {}

# ZAMAN MAKİNESİ (GERİ AL HAFIZASI)
hamle_gecmisi = []

tahta = [
    ['r', 'n', 'b', 'q', 'k', 'b', 'n', 'r'],
    ['p', 'p', 'p', 'p', 'p', 'p', 'p', 'p'],
    [' ', ' ', ' ', ' ', ' ', ' ', ' ', ' '],
    [' ', ' ', ' ', ' ', ' ', ' ', ' ', ' '],
    [' ', ' ', ' ', ' ', ' ', ' ', ' ', ' '],
    [' ', ' ', ' ', ' ', ' ', ' ', ' ', ' '],
    ['P', 'P', 'P', 'P', 'P', 'P', 'P', 'P'],
    ['R', 'N', 'B', 'Q', 'K', 'B', 'N', 'R']
]

beyaz_skor, siyah_skor = 0, 0
yenilen_beyazlar, yenilen_siyahlar = [], []


# =====================================================================
# 2. VERİTABANI VE ŞİFRELEME (ANTI-CHEAT) BÖLÜMÜ
# =====================================================================
DB_ANAHTAR = "GOALTECH_GIZLI"

def xor_kripto(metin, anahtar):
    metin_str = str(metin)
    sonuc = ""
    for i in range(len(metin_str)):
        harf = metin_str[i]
        anahtar_harfi = anahtar[i % len(anahtar)]
        sonuc += chr(ord(harf) ^ ord(anahtar_harfi))
    return sonuc

def veritabanini_kur():
    baglanti = sqlite3.connect("goaltech_chess.db")
    imlec = baglanti.cursor()
    imlec.execute("""
        CREATE TABLE IF NOT EXISTS Mac_Gecmisi (
            mac_id INTEGER PRIMARY KEY AUTOINCREMENT,
            oyuncu TEXT,
            beyaz_puan TEXT,
            siyah_puan TEXT,
            kazanan TEXT,
            tarih DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)
    baglanti.commit()
    baglanti.close()

def mac_kaydet(oyuncu_adi, b_skor, s_skor, kazanan_taraf):
    try:
        s_oyuncu = xor_kripto(oyuncu_adi, DB_ANAHTAR)
        s_kazanan = xor_kripto(kazanan_taraf, DB_ANAHTAR)
        s_beyaz = xor_kripto(b_skor, DB_ANAHTAR)
        s_siyah = xor_kripto(s_skor, DB_ANAHTAR)
        
        baglanti = sqlite3.connect("goaltech_chess.db")
        imlec = baglanti.cursor()
        imlec.execute("""
            INSERT INTO Mac_Gecmisi (oyuncu, beyaz_puan, siyah_puan, kazanan)
            VALUES (?, ?, ?, ?)
        """, (s_oyuncu, s_beyaz, s_siyah, s_kazanan))
        baglanti.commit()
        baglanti.close()
        print("VERİTABANI: Maç sonucu başarıyla şifrelenip kaydedildi!")
    except Exception as e:
        print("VERİTABANI HATASI:", e)

veritabanini_kur()


# =====================================================================
# 3. TAM KAPSAMLI SATRANÇ KURAL MOTORU
# =====================================================================
def yol_acik_mi(b_sat, b_sut, h_sat, h_sut):
    adim_sat = 0 if h_sat == b_sat else (1 if h_sat > b_sat else -1)
    adim_sut = 0 if h_sut == b_sut else (1 if h_sut > b_sut else -1)
    g_sat, g_sut = b_sat + adim_sat, b_sut + adim_sut

    while (g_sat, g_sut) != (h_sat, h_sut):
        if tahta[g_sat][g_sut] != ' ':
            return False
        g_sat += adim_sat
        g_sut += adim_sut
    return True

def sah_konumu_bul(beyaz_mi):
    aranan_sah = 'K' if beyaz_mi else 'k'
    for r in range(8):
        for c in range(8):
            if tahta[r][c] == aranan_sah:
                return r, c
    return -1, -1

def tehdit_altinda_mi(satir, sutun, saldirgan_beyaz_mi):
    for r in range(8):
        for c in range(8):
            tas = tahta[r][c]
            if tas != ' ' and tas.isupper() == saldirgan_beyaz_mi:
                if tas.upper() == 'P':
                    yon = -1 if tas.isupper() else 1
                    if satir - r == yon and abs(sutun - c) == 1:
                        return True
                else:
                    if kural_kontrol_ham(tas, r, c, satir, sutun):
                        return True
    return False

def kural_kontrol_ham(tas, b_sat, b_sut, h_sat, h_sut):
    tip = tas.upper()
    df_sat = abs(h_sat - b_sat)
    df_sut = abs(h_sut - b_sut)
    hedef = tahta[h_sat][h_sut]

    if tip == 'P':
        yon = -1 if tas.isupper() else 1
        baslangic = 6 if tas.isupper() else 1
        if b_sut == h_sut and hedef == ' ':
            if h_sat - b_sat == yon:
                return True
            if b_sat == baslangic and h_sat - b_sat == 2 * yon and tahta[b_sat + yon][b_sut] == ' ':
                return True
        if df_sut == 1 and h_sat - b_sat == yon and hedef != ' ':
            return True
        if df_sut == 1 and h_sat - b_sat == yon and hedef == ' ':
            if gecerken_alinabilir_kare == (h_sat, h_sut):
                return True
        return False

    elif tip == 'R':
        return (b_sat == h_sat or b_sut == h_sut) and yol_acik_mi(b_sat, b_sut, h_sat, h_sut)
    elif tip == 'B':
        return (df_sat == df_sut) and yol_acik_mi(b_sat, b_sut, h_sat, h_sut)
    elif tip == 'Q':
        return (b_sat == h_sat or b_sut == h_sut or df_sat == df_sut) and yol_acik_mi(b_sat, b_sut, h_sat, h_sut)
    elif tip == 'N':
        return (df_sat == 2 and df_sut == 1) or (df_sat == 1 and df_sut == 2)
    elif tip == 'K':
        return df_sat <= 1 and df_sut <= 1
    return False

def kural_kontrol(tas, b_sat, b_sut, h_sat, h_sut):
    tip = tas.upper()
    if kural_kontrol_ham(tas, b_sat, b_sut, h_sat, h_sut):
        return True

    # ROK (CASTLING) KONTROLÜ
    if tip == 'K' and b_sat == h_sat and abs(h_sut - b_sut) == 2:
        beyaz_mi = tas.isupper()
        if beyaz_mi and (b_sat, b_sut) == (7, 4):
            if beyaz_sah_oynadi or tehdit_altinda_mi(7, 4, False):
                return False
            if h_sut == 6:  # Beyaz Kısa Rok
                if beyaz_kale_sag_oynadi or tahta[7][7] != 'R':
                    return False
                if tahta[7][5] != ' ' or tahta[7][6] != ' ':
                    return False
                if tehdit_altinda_mi(7, 5, False) or tehdit_altinda_mi(7, 6, False):
                    return False
                return True
            elif h_sut == 2:  # Beyaz Uzun Rok
                if beyaz_kale_sol_oynadi or tahta[7][0] != 'R':
                    return False
                if tahta[7][1] != ' ' or tahta[7][2] != ' ' or tahta[7][3] != ' ':
                    return False
                if tehdit_altinda_mi(7, 3, False) or tehdit_altinda_mi(7, 2, False):
                    return False
                return True

        elif not beyaz_mi and (b_sat, b_sut) == (0, 4):
            if siyah_sah_oynadi or tehdit_altinda_mi(0, 4, True):
                return False
            if h_sut == 6:  # Siyah Kısa Rok
                if siyah_kale_sag_oynadi or tahta[0][7] != 'r':
                    return False
                if tahta[0][5] != ' ' or tahta[0][6] != ' ':
                    return False
                if tehdit_altinda_mi(0, 5, True) or tehdit_altinda_mi(0, 6, True):
                    return False
                return True
            elif h_sut == 2:  # Siyah Uzun Rok
                if siyah_kale_sol_oynadi or tahta[0][0] != 'r':
                    return False
                if tahta[0][1] != ' ' or tahta[0][2] != ' ' or tahta[0][3] != ' ':
                    return False
                if tehdit_altinda_mi(0, 3, True) or tehdit_altinda_mi(0, 2, True):
                    return False
                return True

    return False

def gecerli_hamleleri_bul(b_sat, b_sut, beyaz_sirasi):
    secilen = tahta[b_sat][b_sut]
    hamleler = []
    
    for h_sat in range(8):
        for h_sut in range(8):
            hedef_tas = tahta[h_sat][h_sut]
            if hedef_tas == ' ' or hedef_tas.isupper() != beyaz_sirasi:
                if kural_kontrol(secilen, b_sat, b_sut, h_sat, h_sut):
                    gecici_hedef = tahta[h_sat][h_sut]
                    
                    alinan_en_passant_tas = ' '
                    en_passant_yapiliyor = False
                    if secilen.upper() == 'P' and abs(h_sut - b_sut) == 1 and gecici_hedef == ' ':
                        en_passant_yapiliyor = True
                        yon = -1 if beyaz_sirasi else 1
                        alinan_en_passant_tas = tahta[h_sat - yon][h_sut]
                        tahta[h_sat - yon][h_sut] = ' '

                    tahta[h_sat][h_sut] = secilen
                    tahta[b_sat][b_sut] = ' '
                    
                    roklu_mu = False
                    kale_eski_pos, kale_yeni_pos = None, None
                    if secilen.upper() == 'K' and abs(h_sut - b_sut) == 2:
                        roklu_mu = True
                        if h_sut == 6:
                            kale_eski_pos = (h_sat, 7)
                            kale_yeni_pos = (h_sat, 5)
                        elif h_sut == 2:
                            kale_eski_pos = (h_sat, 0)
                            kale_yeni_pos = (h_sat, 3)
                        tahta[kale_yeni_pos[0]][kale_yeni_pos[1]] = tahta[kale_eski_pos[0]][kale_eski_pos[1]]
                        tahta[kale_eski_pos[0]][kale_eski_pos[1]] = ' '

                    sah_sat, sah_sut = sah_konumu_bul(beyaz_sirasi)
                    rakip_beyaz = not beyaz_sirasi
                    if not tehdit_altinda_mi(sah_sat, sah_sut, rakip_beyaz):
                        hamleler.append((h_sat, h_sut))
                        
                    if roklu_mu:
                        tahta[kale_eski_pos[0]][kale_eski_pos[1]] = tahta[kale_yeni_pos[0]][kale_yeni_pos[1]]
                        tahta[kale_yeni_pos[0]][kale_yeni_pos[1]] = ' '
                    if en_passant_yapiliyor:
                        yon = -1 if beyaz_sirasi else 1
                        tahta[h_sat - yon][h_sut] = alinan_en_passant_tas
                    tahta[b_sat][b_sut] = secilen
                    tahta[h_sat][h_sut] = gecici_hedef
    return hamleler

def tum_gecerli_hamlelerin_sayisi(beyaz_sirasi):
    toplam = 0
    for r in range(8):
        for c in range(8):
            tas = tahta[r][c]
            if tas != ' ' and tas.isupper() == beyaz_sirasi:
                toplam += len(gecerli_hamleleri_bul(r, c, beyaz_sirasi))
    return toplam

def yetersiz_materyal_mi():
    taslar = []
    fil_renkleri = []
    for r in range(8):
        for c in range(8):
            t = tahta[r][c]
            if t != ' ' and t.upper() != 'K':
                taslar.append(t.upper())
                if t.upper() == 'B':
                    fil_renkleri.append((r + c) % 2)
    if len(taslar) == 0:
        return True
    if len(taslar) == 1 and taslar[0] in ['N', 'B']:
        return True
    if len(taslar) == 2 and taslar == ['B', 'B'] and fil_renkleri[0] == fil_renkleri[1]:
        return True
    return False

def tahta_durum_anahtari(beyaz_sirasi):
    tahta_str = "".join("".join(satir) for satir in tahta)
    rok_str = f"{beyaz_sah_oynadi}{beyaz_kale_sol_oynadi}{beyaz_kale_sag_oynadi}{siyah_sah_oynadi}{siyah_kale_sol_oynadi}{siyah_kale_sag_oynadi}"
    return f"{tahta_str}_{beyaz_sirasi}_{rok_str}_{gecerken_alinabilir_kare}"


# =====================================================================
# 4. JWT (TOKEN) VE GİRİŞ BİLGİLERİ
# =====================================================================
KAYITLI_KULLANICI = "vahit"
KAYITLI_SIFRE = "yasin12345"        
SECRET_KEY = "goaltech_secret_key"

def token_uret(kullanici_adi):
    payload = {
        "oyuncu": kullanici_adi,
        "oyun": "Goaltech Chess",
        "exp": int(time.time()) + 3600
    }
    res = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
    return res if isinstance(res, str) else res.decode('utf-8')


# =====================================================================
# 5. PYGAME TAM EKRAN AYARLARI
# =====================================================================

import os

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
