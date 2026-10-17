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

GENISLIK, YUKSEKLIK = ekran.get_size()

KARE_BOYUTU = min(GENISLIK, YUKSEKLIK - 200) // 8
BASLANGIC_X = (GENISLIK - (8 * KARE_BOYUTU)) // 2
BASLANGIC_Y = (YUKSEKLIK - (8 * KARE_BOYUTU)) // 2 + 30



# =====================================================================
# 6. ANA OYUN VE ARAYÜZ DÖNGÜSÜ
# =====================================================================
def oyunu_sifirla():
    global tahta, beyaz_skor, siyah_skor, beyaz_sirasi
    global beyaz_sah_oynadi, beyaz_kale_sol_oynadi, beyaz_kale_sag_oynadi
    global siyah_sah_oynadi, siyah_kale_sol_oynadi, siyah_kale_sag_oynadi
    global gecerken_alinabilir_kare, elli_hamle_sayaci, konum_gecmisi, hamle_gecmisi

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
    yenilen_beyazlar.clear()
    yenilen_siyahlar.clear()
    hamle_gecmisi.clear()
    beyaz_sirasi = True
    beyaz_sah_oynadi = beyaz_kale_sol_oynadi = beyaz_kale_sag_oynadi = False
    siyah_sah_oynadi = siyah_kale_sol_oynadi = siyah_kale_sag_oynadi = False
    gecerken_alinabilir_kare = None
    elli_hamle_sayaci = 0
    konum_gecmisi.clear()
    anahtar = tahta_durum_anahtari(True)
    konum_gecmisi[anahtar] = 1

def arayuzu_baslat():
    global beyaz_skor, siyah_skor, tahta, beyaz_sirasi
    global beyaz_sah_oynadi, beyaz_kale_sol_oynadi, beyaz_kale_sag_oynadi
    global siyah_sah_oynadi, siyah_kale_sol_oynadi, siyah_kale_sag_oynadi
    global gecerken_alinabilir_kare, elli_hamle_sayaci

    oyun_durumu = "LOGIN"
    
    girilen_ad = ""
    girilen_sifre = ""
    aktif_kutu = "ad"
    hata_mesaji = ""
    aktif_token = None

    secili_kare = None
    olasi_hamleler = []
    son_hamle = "Oyun başladı. Hamle sırası Beyazda."
    kazanan = None
    terfi_bekleyen = None

    kart_gen, kart_yuk = 460, 430
    kart_x = (GENISLIK - kart_gen) // 2
    kart_y = (YUKSEKLIK - kart_yuk) // 2 + 60

    
    # GERİ AL (UNDO) BUTONU KOORDİNATLARI (Üst panelin sağ tarafı)

    vitrin_taslari = ['♔', '♕', '♖', '♗', '♘', '♙']

    def hamle_sonrasi_kontrol():
        nonlocal kazanan, son_hamle
        global beyaz_sirasi

        beyaz_sirasi = not beyaz_sirasi
        
        anahtar = tahta_durum_anahtari(beyaz_sirasi)
        konum_gecmisi[anahtar] = konum_gecmisi.get(anahtar, 0) + 1

        sah_r, sah_c = sah_konumu_bul(beyaz_sirasi)
        sah_tehdidi = tehdit_altinda_mi(sah_r, sah_c, not beyaz_sirasi)
        yasal_hamle_sayisi = tum_gecerli_hamlelerin_sayisi(beyaz_sirasi)

        if yasal_hamle_sayisi == 0:
            if sah_tehdidi:
                kazanan = "BEYAZ" if not beyaz_sirasi else "SİYAH"
                son_hamle = f"ŞAH MAT! Oyunu {kazanan} kazandı!"
            else:
                kazanan = "BERABERE"
                son_hamle = "OYUN BİTTİ! PAT (Yapılacak hamle kalmadı - Berabere)."
            mac_kaydet(KAYITLI_KULLANICI, beyaz_skor, siyah_skor, kazanan)
        elif elli_hamle_sayaci >= 100:
            kazanan = "BERABERE"
            son_hamle = "OYUN BİTTİ! 50 Hamle Kuralı sebebiyle Berabere."
            mac_kaydet(KAYITLI_KULLANICI, beyaz_skor, siyah_skor, kazanan)
        elif konum_gecmisi[anahtar] >= 3:
            kazanan = "BERABERE"
            son_hamle = "OYUN BİTTİ! 3 Kez Konum Tekrarı sebebiyle Berabere."
            mac_kaydet(KAYITLI_KULLANICI, beyaz_skor, siyah_skor, kazanan)
        elif yetersiz_materyal_mi():
            kazanan = "BERABERE"
            son_hamle = "OYUN BİTTİ! Yetersiz Materyal sebebiyle Berabere."
            mac_kaydet(KAYITLI_KULLANICI, beyaz_skor, siyah_skor, kazanan)
        elif sah_tehdidi:
            son_hamle += " — ŞAH!"

    calisiyor = True
    while calisiyor:
        zaman = time.time()
        ekran.fill(ARKAPLAN_RENK)

                calisiyor = False

                if oyun_durumu == "OYUN":
                    oyun_durumu = "LOGIN"
                    girilen_sifre = ""
                    hata_mesaji = ""
                    terfi_bekleyen = None
                else:
                    calisiyor = False  

                if cikis_btn_rect.collidepoint(olay.pos):
                    if oyun_durumu == "OYUN":
                        oyun_durumu = "LOGIN"
                        girilen_sifre = ""
                        hata_mesaji = ""
                        terfi_bekleyen = None
                    else:
                        calisiyor = False  

                # --- GERİ AL (UNDO) BUTONUNA BASILDIĞINDA ---
                elif oyun_durumu == "OYUN" and geri_al_btn_rect.collidepoint(olay.pos):
                    if hamle_gecmisi:
                        eski_durum = hamle_gecmisi.pop()
                        tahta = eski_durum['tahta']
                        beyaz_sirasi = eski_durum['sira']
                        beyaz_skor = eski_durum['b_skor']
                        siyah_skor = eski_durum['s_skor']
                        yenilen_beyazlar = eski_durum['y_beyaz']
                        yenilen_siyahlar = eski_durum['y_siyah']
                        son_hamle = eski_durum['son_hamle']
                        beyaz_sah_oynadi = eski_durum['b_sah']
                        beyaz_kale_sol_oynadi = eski_durum['b_k_sol']
                        beyaz_kale_sag_oynadi = eski_durum['b_k_sag']
                        siyah_sah_oynadi = eski_durum['s_sah']
                        siyah_kale_sol_oynadi = eski_durum['s_k_sol']
                        siyah_kale_sag_oynadi = eski_durum['s_k_sag']
                        gecerken_alinabilir_kare = eski_durum['gecerken']
                        elli_hamle_sayaci = eski_durum['elli_sayac']
                        kazanan = None
                        secili_kare = None
                        olasi_hamleler = []
                        terfi_bekleyen = None

            if oyun_durumu == "LOGIN":
                    if ad_kutu_rect.collidepoint(olay.pos):
                        aktif_kutu = "ad"
                    elif sifre_kutu_rect.collidepoint(olay.pos):
                        aktif_kutu = "sifre"
                    elif giris_btn_rect.collidepoint(olay.pos):
                        if girilen_ad == KAYITLI_KULLANICI and girilen_sifre == KAYITLI_SIFRE:
                            aktif_token = token_uret(girilen_ad)
                            oyun_durumu = "OYUN"
                            oyunu_sifirla()
                            kazanan = None
                            secili_kare = None
                            olasi_hamleler = []
                            terfi_bekleyen = None
                            son_hamle = "Oyun başladı. Hamle sırası Beyazda."
                        else:
                            hata_mesaji = "Hatalı kullanıcı adı veya şifre!"

                        aktif_kutu = "sifre" if aktif_kutu == "ad" else "ad"
                        if girilen_ad == KAYITLI_KULLANICI and girilen_sifre == KAYITLI_SIFRE:
                            aktif_token = token_uret(girilen_ad)
                            oyun_durumu = "OYUN"
                            oyunu_sifirla()
                            kazanan = None
                            secili_kare = None
                            olasi_hamleler = []
                            terfi_bekleyen = None
                            son_hamle = "Oyun başladı. Hamle sırası Beyazda."
                        else:
                            hata_mesaji = "Hatalı kullanıcı adı veya şifre!"
                        if aktif_kutu == "ad":
                            girilen_ad = girilen_ad[:-1]
                        else:
                            girilen_sifre = girilen_sifre[:-1]
                        if aktif_kutu == "ad" and len(girilen_ad) < 20:
                            girilen_ad += olay.unicode
                        elif aktif_kutu == "sifre" and len(girilen_sifre) < 20:
                            girilen_sifre += olay.unicode

            elif oyun_durumu == "OYUN" and not kazanan:
                if terfi_bekleyen:
                        mx, my = olay.pos
                        p_sat, p_sut, p_beyaz = terfi_bekleyen
                        secenekler = ['Q', 'R', 'B', 'N'] if p_beyaz else ['q', 'r', 'b', 'n']
                        menu_w = 4 * KARE_BOYUTU
                        menu_h = KARE_BOYUTU + 45
                        menu_x = (GENISLIK - menu_w) // 2
                        menu_y = (YUKSEKLIK - menu_h) // 2

                        for i, secenek_tas in enumerate(secenekler):
                            if kutu_rect.collidepoint(mx, my):
                                tahta[p_sat][p_sut] = secenek_tas
                                son_hamle += f" (Terfi: {TAS_ISIMLERI[secenek_tas.upper()]})"
                                terfi_bekleyen = None
                                hamle_sonrasi_kontrol()
                                break
                    continue

                    mx, my = olay.pos

                    # TAHTA ÜZERİNE TIKLAMA KONTROLÜ (Geri al butonuna basılmadıysa)
                    if not geri_al_btn_rect.collidepoint(olay.pos) and BASLANGIC_X <= mx < BASLANGIC_X + 8 * KARE_BOYUTU and BASLANGIC_Y <= my < BASLANGIC_Y + 8 * KARE_BOYUTU:
                        sutun = (mx - BASLANGIC_X) // KARE_BOYUTU
                        satir = (my - BASLANGIC_Y) // KARE_BOYUTU

                        if secili_kare and (satir, sutun) in olasi_hamleler:
                            b_sat, b_sut = secili_kare
                            h_sat, h_sut = satir, sutun
                            secilen = tahta[b_sat][b_sut]
                            hedef_tas = tahta[h_sat][h_sut]

                            # 1. HAMLE ÖNCESİ DURUMU HAFIZAYA KAYDET (Zaman Makinesi için)
                            hamle_gecmisi.append({
                                'tahta': [satir_kopya[:] for satir_kopya in tahta],
                                'sira': beyaz_sirasi,
                                'b_skor': beyaz_skor,
                                's_skor': siyah_skor,
                                'y_beyaz': list(yenilen_beyazlar),
                                'y_siyah': list(yenilen_siyahlar),
                                'son_hamle': son_hamle,
                                'b_sah': beyaz_sah_oynadi,
                                'b_k_sol': beyaz_kale_sol_oynadi,
                                'b_k_sag': beyaz_kale_sag_oynadi,
                                's_sah': siyah_sah_oynadi,
                                's_k_sol': siyah_kale_sol_oynadi,
                                's_k_sag': siyah_kale_sag_oynadi,
                                'gecerken': gecerken_alinabilir_kare,
                                'elli_sayac': elli_hamle_sayaci
                            })

                            tas_yendi_mi = False
                            yeni_gecerken_kare = None
                            if secilen.upper() == 'P':
                                yon = -1 if beyaz_sirasi else 1
                                if abs(h_sat - b_sat) == 2:
                                    yeni_gecerken_kare = (b_sat + yon, b_sut)
                                if abs(h_sut - b_sut) == 1 and hedef_tas == ' ' and gecerken_alinabilir_kare == (h_sat, h_sut):
                                    alinan_p_sat = h_sat - yon
                                    alinan_p_sut = h_sut
                                    alinan_tas = tahta[alinan_p_sat][alinan_p_sut]
                                    tahta[alinan_p_sat][alinan_p_sut] = ' '
                                    tas_yendi_mi = True
                                    puan = TAS_PUANLARI['P']
                                    if beyaz_sirasi:
                                        beyaz_skor += puan
                                        yenilen_siyahlar.append(SEMBOLLER[alinan_tas])
                                    else:
                                        siyah_skor += puan
                                        yenilen_beyazlar.append(SEMBOLLER[alinan_tas])

                            gecerken_alinabilir_kare = yeni_gecerken_kare

                            if hedef_tas != ' ':
                                tas_yendi_mi = True
                                puan = TAS_PUANLARI[hedef_tas.upper()]
                                if beyaz_sirasi:
                                    beyaz_skor += puan
                                    yenilen_siyahlar.append(SEMBOLLER[hedef_tas])
                                else:
                                    siyah_skor += puan
                                    yenilen_beyazlar.append(SEMBOLLER[hedef_tas])
                            
                            if secilen.upper() == 'P' or tas_yendi_mi:
                                elli_hamle_sayaci = 0
                            else:
                                elli_hamle_sayaci += 1

                            # DOĞAL ROK İŞLEMİ (Şah 2 kare kaydıysa kaleyi otomatik taşı)
                            rok_yapildi_mi = False
                            if secilen.upper() == 'K' and abs(h_sut - b_sut) == 2:
                                rok_yapildi_mi = True
                                if h_sut == 6:
                                    tahta[h_sat][5] = tahta[h_sat][7]
                                    tahta[h_sat][7] = ' '
                                elif h_sut == 2:
                                    tahta[h_sat][3] = tahta[h_sat][0]
                                    tahta[h_sat][0] = ' '

                            tahta[h_sat][h_sut] = secilen
                            tahta[b_sat][b_sut] = ' '

                            # Hak ve Bayrak Güncellemeleri
                            if secilen == 'K': beyaz_sah_oynadi = True
                            elif secilen == 'k': siyah_sah_oynadi = True
                            elif secilen == 'R':
                                if (b_sat, b_sut) == (7, 0): beyaz_kale_sol_oynadi = True
                                elif (b_sat, b_sut) == (7, 7): beyaz_kale_sag_oynadi = True
                            elif secilen == 'r':
                                if (b_sat, b_sut) == (0, 0): siyah_kale_sol_oynadi = True
                                elif (b_sat, b_sut) == (0, 7): siyah_kale_sag_oynadi = True

                            if (h_sat, h_sut) == (7, 0): beyaz_kale_sol_oynadi = True
                            elif (h_sat, h_sut) == (7, 7): beyaz_kale_sag_oynadi = True
                            elif (h_sat, h_sut) == (0, 0): siyah_kale_sol_oynadi = True
                            elif (h_sat, h_sut) == (0, 7): siyah_kale_sag_oynadi = True

                            bas_k = f"{chr(ord('a') + b_sut)}{8 - b_sat}"
                            hed_k = f"{chr(ord('a') + h_sut)}{8 - h_sat}"
                            if rok_yapildi_mi:
                                rok_tipi = "Kısa Rok" if h_sut == 6 else "Uzun Rok"
                                son_hamle = f"Son Hamle: {rok_tipi} ({bas_k} -> {hed_k})"
                            else:
                                son_hamle = f"Son Hamle: {TAS_ISIMLERI[secilen.upper()]} ({bas_k} -> {hed_k})"

                            secili_kare = None
                            olasi_hamleler = []

                            if (secilen == 'P' and h_sat == 0) or (secilen == 'p' and h_sat == 7):
                                terfi_bekleyen = (h_sat, h_sut, beyaz_sirasi)
                            else:
                                hamle_sonrasi_kontrol()

                        elif tahta[satir][sutun] != ' ' and tahta[satir][sutun].isupper() == beyaz_sirasi:
                            secili_kare = (satir, sutun)
                            olasi_hamleler = gecerli_hamleleri_bul(satir, sutun, beyaz_sirasi)
                        else:
                            secili_kare = None
                            olasi_hamleler = []

        # =====================================================================
        # EKRAN ÇİZİMLERİ
        # =====================================================================
        if oyun_durumu == "LOGIN":
            bg_kare = 100
            for r in range(0, YUKSEKLIK, bg_kare):
                for c in range(0, GENISLIK, bg_kare):
                    if ((r // bg_kare) + (c // bg_kare)) % 2 == 0:

            toplam_vitrin_gen = len(vitrin_taslari) * 85
            vitrin_bas_x = (GENISLIK - toplam_vitrin_gen) // 2 + 20
            for i, sembol in enumerate(vitrin_taslari):
                salinim_y = math.sin(zaman * 3 + i * 0.8) * 10
                renk = BEYAZ_TAS_RENK if i % 2 == 0 else SIYAH_TAS_RENK
                tas_yuzey = font_dev_tas.render(sembol, True, renk)
                ekran.blit(tas_yuzey, (vitrin_bas_x + i * 85, kart_y - 190 + salinim_y))

            baslik_golge = font_baslik.render("GOALTECH CHESS", True, (0, 0, 0))
            baslik = font_baslik.render("GOALTECH CHESS", True, BEYAZ)
            ekran.blit(baslik_golge, (GENISLIK // 2 - baslik.get_width() // 2 + 3, kart_y - 105 + 3))
            ekran.blit(baslik, (GENISLIK // 2 - baslik.get_width() // 2, kart_y - 105))

            alt_baslik = font_alt_baslik.render("Güvenli Oyuncu Giriş Portalı", True, (140, 150, 165))
            ekran.blit(alt_baslik, (GENISLIK // 2 - alt_baslik.get_width() // 2, kart_y - 42))


            imlec = "|" if int(zaman * 2) % 2 == 0 else ""

            ekran.blit(font_normal.render("KULLANICI ADI", True, GRI), (ad_kutu_rect.x, ad_kutu_rect.y - 30))
            cerceve_ad = (0, 180, 200) if aktif_kutu == "ad" else (60, 70, 85)
            ad_metin = girilen_ad + (imlec if aktif_kutu == "ad" else "")
            ekran.blit(font_yazi.render(ad_metin, True, BEYAZ), (ad_kutu_rect.x + 15, ad_kutu_rect.y + 12))

            ekran.blit(font_normal.render("ŞİFRE", True, GRI), (sifre_kutu_rect.x, sifre_kutu_rect.y - 30))
            cerceve_sifre = (0, 180, 200) if aktif_kutu == "sifre" else (60, 70, 85)
            sifre_metin = ("●" * len(girilen_sifre)) + (imlec if aktif_kutu == "sifre" else "")
            ekran.blit(font_yazi.render(sifre_metin, True, (0, 180, 200)), (sifre_kutu_rect.x + 15, sifre_kutu_rect.y + 12))

            btn_hover = giris_btn_rect.collidepoint(fare_pos)
            btn_renk = (235, 115, 20) if btn_hover else (150, 60, 0)
            btn_yazi = font_normal.render("OYUNA GİRİŞ YAP  ➔", True, BEYAZ)
            ekran.blit(btn_yazi, (giris_btn_rect.centerx - btn_yazi.get_width() // 2, giris_btn_rect.centery - btn_yazi.get_height() // 2))

            if hata_mesaji:
                uyari = font_yazi.render(hata_mesaji, True, UYARI_RENK)
                ekran.blit(uyari, (GENISLIK // 2 - uyari.get_width() // 2, kart_y + 370))

        elif oyun_durumu == "OYUN":

            sira_metni = "SIRA: BEYAZ" if beyaz_sirasi else "SIRA: SİYAH"
            sira_renk = BEYAZ_TAS_RENK if beyaz_sirasi else (160, 160, 160)
            ekran.blit(font_normal.render(sira_metni, True, sira_renk), (ust_panel.x + 20, ust_panel.y + 12))
            ekran.blit(font_yazi.render(son_hamle, True, UYARI_RENK if kazanan else BEYAZ), (ust_panel.x + 190, ust_panel.y + 14))

            skor_b = font_kucuk.render(f"Beyaz ({beyaz_skor} Puan) Aldıkları: {' '.join(yenilen_siyahlar)}", True, BEYAZ_TAS_RENK)
            skor_s = font_kucuk.render(f"Siyah ({siyah_skor} Puan) Aldıkları: {' '.join(yenilen_beyazlar)}", True, (150, 150, 150))
            ekran.blit(skor_b, (ust_panel.x + 20, ust_panel.y + 50))
            ekran.blit(skor_s, (ust_panel.x + 340, ust_panel.y + 50))


            aktif_sah_r, aktif_sah_c = sah_konumu_bul(beyaz_sirasi)
            aktif_sah_tehditte = tehdit_altinda_mi(aktif_sah_r, aktif_sah_c, not beyaz_sirasi)

            for satir in range(8):
                sayi_yazi = font_kucuk.render(str(8 - satir), True, GRI)
                ekran.blit(sayi_yazi, (BASLANGIC_X - 22, BASLANGIC_Y + satir * KARE_BOYUTU + KARE_BOYUTU // 2 - 8))

                for sutun in range(8):
                    kare_renk = ACIK_KARE if (satir + sutun) % 2 == 0 else KOYU_KARE
                    if aktif_sah_tehditte and (satir, sutun) == (aktif_sah_r, aktif_sah_c):
                        kare_renk = SAH_TEHDIT_RENK
                    elif secili_kare == (satir, sutun):
                        kare_renk = SARI_SECIM

                    x = BASLANGIC_X + sutun * KARE_BOYUTU
                    y = BASLANGIC_Y + satir * KARE_BOYUTU

                    tas = tahta[satir][sutun]
                    if tas != ' ':
                        tas_renk = BEYAZ_TAS_RENK if tas.isupper() else SIYAH_TAS_RENK
                        sembol_yazi = font_sembol.render(SEMBOLLER[tas], True, tas_renk)
                        sembol_rect = sembol_yazi.get_rect(center=(x + KARE_BOYUTU // 2, y + KARE_BOYUTU // 2))
                        ekran.blit(sembol_yazi, sembol_rect)

            for sutun in range(8):
                harf_yazi = font_kucuk.render(chr(ord('a') + sutun), True, GRI)
                ekran.blit(harf_yazi, (BASLANGIC_X + sutun * KARE_BOYUTU + KARE_BOYUTU // 2 - 5, BASLANGIC_Y + 8 * KARE_BOYUTU + 6))

            for (h_sat, h_sut) in olasi_hamleler:
                merkez_x = BASLANGIC_X + h_sut * KARE_BOYUTU + KARE_BOYUTU // 2
                merkez_y = BASLANGIC_Y + h_sat * KARE_BOYUTU + KARE_BOYUTU // 2

            # --- GERİ AL (UNDO) BUTONU ÇİZİMİ ---
            geri_al_hover = geri_al_btn_rect.collidepoint(fare_pos)
            geri_al_renk = (70, 130, 180) if geri_al_hover else (40, 90, 130)
            geri_al_yazi = font_kucuk.render("↩ HAMLEYİ GERİ AL", True, BEYAZ)
            ekran.blit(geri_al_yazi, (geri_al_btn_rect.centerx - geri_al_yazi.get_width() // 2, geri_al_btn_rect.centery - geri_al_yazi.get_height() // 2))

            # Piyon Terfi Seçim Penceresi
            if terfi_bekleyen:
                p_sat, p_sut, p_beyaz = terfi_bekleyen
                secenekler = ['Q', 'R', 'B', 'N'] if p_beyaz else ['q', 'r', 'b', 'n']
                menu_w = 4 * KARE_BOYUTU
                menu_h = KARE_BOYUTU + 45
                menu_x = (GENISLIK - menu_w) // 2
                menu_y = (YUKSEKLIK - menu_h) // 2

                
                baslik_terfi = font_kucuk.render("PİYON TERFİSİ: Yeni Taşı Seçin", True, BEYAZ)
                ekran.blit(baslik_terfi, (GENISLIK // 2 - baslik_terfi.get_width() // 2, menu_y))

                for i, secenek_tas in enumerate(secenekler):
                    kutu_renk = SARI_SECIM if kutu_rect.collidepoint(fare_pos) else ACIK_KARE

                    t_renk = BEYAZ_TAS_RENK if p_beyaz else SIYAH_TAS_RENK
                    s_yazi = font_sembol.render(SEMBOLLER[secenek_tas], True, t_renk)
                    s_rect = s_yazi.get_rect(center=kutu_rect.center)
                    ekran.blit(s_yazi, s_rect)

            token_bilgi = font_kucuk.render(f"Aktif Oyuncu: {KAYITLI_KULLANICI.upper()}  |  JWT Bilet: {aktif_token[:55]}...", True, GRI)
            ekran.blit(token_bilgi, (BASLANGIC_X, YUKSEKLIK - 30))

        # Sağ Üst Çıkış/Girişe Dön Butonu
        cikis_yazi = font_kucuk.render("GİRİŞE DÖN" if oyun_durumu == "OYUN" else "ÇIKIŞ (ESC)", True, BEYAZ)
        ekran.blit(cikis_yazi, (cikis_btn_rect.centerx - cikis_yazi.get_width() // 2, cikis_btn_rect.centery - cikis_yazi.get_height() // 2))

        saat.tick(60)


if __name__ == "__main__":
    arayuzu_baslat()
import os

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
