import os
import time
import sqlite3
import threading
import random
import copy
from flask import Flask, jsonify, request

app = Flask(__name__)

# =====================================================================
# 1. VERİTABANI VE ŞİFRELEME
# =====================================================================
DB_ANAHTAR = "GOALTECH_GIZLI"
DB_YOLU = os.path.join(os.path.dirname(os.path.abspath(__file__)), "goaltech_chess.db")

def xor_kripto(metin, anahtar):
    metin_str = str(metin)
    return "".join(chr(ord(c) ^ ord(anahtar[i % len(anahtar)])) for i, c in enumerate(metin_str))

def veritabanini_kur():
    baglanti = sqlite3.connect(DB_YOLU)
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
        baglanti = sqlite3.connect(DB_YOLU)
        try:
            imlec = baglanti.cursor()
            imlec.execute("INSERT INTO Mac_Gecmisi (oyuncu, beyaz_puan, siyah_puan, kazanan) VALUES (?, ?, ?, ?)",
                          (xor_kripto(oyuncu_adi, DB_ANAHTAR), xor_kripto(b_skor, DB_ANAHTAR), xor_kripto(s_skor, DB_ANAHTAR), xor_kripto(kazanan_taraf, DB_ANAHTAR)))
            baglanti.commit()
        finally:
            baglanti.close()
    except Exception as e:
        print("DB HATA:", e)

veritabanini_kur()

# =====================================================================
# 2. ODA YÖNETİMİ
# =====================================================================
SEMBOLLER = {'K':'♔','Q':'♕','R':'♖','B':'♗','N':'♘','P':'♙', 'k':'♚','q':'♛','r':'♜','b':'♝','n':'♞','p':'♟',' ':' '}
TAS_PUANLARI = {'P': 1, 'N': 3, 'B': 3, 'R': 5, 'Q': 9, 'K': 0}
IZINLI_DAKIKALAR = (1, 3, 5, 10)
ODA_ZAMAN_ASIMI = 6 * 60 * 60  # 6 saat işlem görmeyen odalar silinir

odalar = {}
kilit = threading.RLock()

def tahta_durum_anahtari(oda):
    t_str = "".join("".join(s) for s in oda['tahta'])
    r_str = f"{oda['b_sah']}{oda['b_k_sol']}{oda['b_k_sag']}{oda['s_sah']}{oda['s_k_sol']}{oda['s_k_sag']}"
    ep = oda['gecerken']
    if ep:
        # Geçerken alma imkânı yoksa bu kare konumu farklılaştırmamalı (FIDE kuralı)
        piyon = 'P' if oda['beyaz_sirasi'] else 'p'
        satir = ep[0] + (1 if oda['beyaz_sirasi'] else -1)
        if not any(0 <= ep[1] + d < 8 and oda['tahta'][satir][ep[1] + d] == piyon for d in (-1, 1)):
            ep = None
    return f"{t_str}_{oda['beyaz_sirasi']}_{r_str}_{ep}"

def yeni_oda_olustur(sure_dakika=3):
    oda = {
        'tahta': [
            ['r', 'n', 'b', 'q', 'k', 'b', 'n', 'r'],
            ['p', 'p', 'p', 'p', 'p', 'p', 'p', 'p'],
            [' ', ' ', ' ', ' ', ' ', ' ', ' ', ' '],
            [' ', ' ', ' ', ' ', ' ', ' ', ' ', ' '],
            [' ', ' ', ' ', ' ', ' ', ' ', ' ', ' '],
            [' ', ' ', ' ', ' ', ' ', ' ', ' ', ' '],
            ['P', 'P', 'P', 'P', 'P', 'P', 'P', 'P'],
            ['R', 'N', 'B', 'Q', 'K', 'B', 'N', 'R']
        ],
        'beyaz_sirasi': True,
        'b_skor': 0,
        's_skor': 0,
        'y_beyaz': [],
        'y_siyah': [],
        'b_sah': False,
        'b_k_sol': False,
        'b_k_sag': False,
        's_sah': False,
        's_k_sol': False,
        's_k_sag': False,
        'gecerken': None,
        'elli_sayac': 0,
        'konum_gecmisi': {},
        'hamle_gecmisi': [],
        'son_hamle': None,
        'mesaj': '',
        'oyun_bitti': False,
        'sonuc_tipi': '',
        'secili_dakika': sure_dakika,
        'beyaz_sure': sure_dakika * 60,
        'siyah_sure': sure_dakika * 60,
        'son_zaman': time.time(),
        'son_erisim': time.time(),
        'oyun_basladi': False,
        'siyah_baglandi': False,
        'beyaz_baglandi': False,
        'beyaz_son': 0,
        'siyah_son': 0,
        'beyaz_id': '',
        'siyah_id': '',
        'chat_sayac': 0,
        'beyaz_ad': '',
        'siyah_ad': '',
        'bot': False,
        'zorluk': 'orta',
        'bot_hesapliyor': False,
        'undo_istegi': None,
        'undo_hamle_no': 0,
        'reset_istegi': None,
        'chat': []
    }
    oda['konum_gecmisi'][tahta_durum_anahtari(oda)] = 1
    return oda

def sadece_sah_var_mi(tahta, beyaz_mi):
    for satir in tahta:
        for t in satir:
            if t != ' ' and t.isupper() == beyaz_mi and t.upper() != 'K':
                return False
    return True

def oyunu_bitir(oda, mesaj, kazanan, sonuc_tipi):
    if oda['oyun_bitti']:
        return
    oda['oyun_bitti'] = True
    oda['oyun_basladi'] = False
    oda['mesaj'] = mesaj
    oda['sonuc_tipi'] = sonuc_tipi
    oyuncular = f"{oda['beyaz_ad'] or 'Beyaz'} vs {oda['siyah_ad'] or 'Siyah'}"
    mac_kaydet(oyuncular, oda['b_skor'], oda['s_skor'], kazanan)

def sure_guncelle(oda):
    if not oda['oyun_basladi'] or oda['oyun_bitti']:
        oda['son_zaman'] = time.time()
        return

    simdi = time.time()
    gecen = simdi - oda['son_zaman']
    oda['son_zaman'] = simdi

    anahtar = 'beyaz_sure' if oda['beyaz_sirasi'] else 'siyah_sure'
    oda[anahtar] = max(0, oda[anahtar] - gecen)
    if oda[anahtar] == 0:
        beyaz_kaybetti = oda['beyaz_sirasi']
        kaybeden = 'Beyazın' if beyaz_kaybetti else 'Siyahın'
        kazanan = 'Siyah' if beyaz_kaybetti else 'Beyaz'
        # Rakibin mat edecek materyali yoksa süre bitimi berabere sayılır
        if sadece_sah_var_mi(oda['tahta'], not beyaz_kaybetti):
            oyunu_bitir(oda, f"{kaybeden} süresi bitti! Rakipte mat materyali yok, Berabere.", "BERABERE", 'berabere')
        else:
            oyunu_bitir(oda, f"{kaybeden} süresi bitti! {kazanan} Kazandı!", kazanan, 'sure')

# =====================================================================
# 3. KURAL MOTORU
# =====================================================================
def yol_acik_mi(tahta, b_sat, b_sut, h_sat, h_sut):
    adim_sat = 0 if h_sat == b_sat else (1 if h_sat > b_sat else -1)
    adim_sut = 0 if h_sut == b_sut else (1 if h_sut > b_sut else -1)
    g_sat, g_sut = b_sat + adim_sat, b_sut + adim_sut
    while (g_sat, g_sut) != (h_sat, h_sut):
        if tahta[g_sat][g_sut] != ' ': return False
        g_sat += adim_sat; g_sut += adim_sut
    return True

def sah_konumu_bul(tahta, beyaz_mi):
    aranan = 'K' if beyaz_mi else 'k'
    for r in range(8):
        for c in range(8):
            if tahta[r][c] == aranan: return r, c
    return -1, -1

def tehdit_altinda_mi(tahta, satir, sutun, saldirgan_beyaz_mi):
    for r in range(8):
        for c in range(8):
            tas = tahta[r][c]
            if tas != ' ' and (tas.isupper() == saldirgan_beyaz_mi):
                if (r, c) == (satir, sutun):
                    continue
                tip = tas.upper()
                df_sat, df_sut = abs(satir - r), abs(sutun - c)
                if tip == 'P':
                    yon = -1 if saldirgan_beyaz_mi else 1
                    if (satir - r == yon) and (df_sut == 1): return True
                elif tip == 'N':
                    if (df_sat == 2 and df_sut == 1) or (df_sat == 1 and df_sut == 2): return True
                elif tip == 'B':
                    if (df_sat == df_sut) and yol_acik_mi(tahta, r, c, satir, sutun): return True
                elif tip == 'R':
                    if (r == satir or c == sutun) and yol_acik_mi(tahta, r, c, satir, sutun): return True
                elif tip == 'Q':
                    if (r == satir or c == sutun or df_sat == df_sut) and yol_acik_mi(tahta, r, c, satir, sutun): return True
                elif tip == 'K':
                    if df_sat <= 1 and df_sut <= 1: return True
    return False

def kural_kontrol(oda, tas, b_sat, b_sut, h_sat, h_sut):
    tahta = oda['tahta']
    if (b_sat, b_sut) == (h_sat, h_sut):
        return False
    tip = tas.upper()
    beyaz_mi = tas.isupper()
    df_sat, df_sut = abs(h_sat - b_sat), abs(h_sut - b_sut)
    hedef = tahta[h_sat][h_sut]

    if tip == 'P':
        yon = -1 if beyaz_mi else 1
        baslangic = 6 if beyaz_mi else 1
        if b_sut == h_sut and hedef == ' ':
            if h_sat - b_sat == yon: return True
            if b_sat == baslangic and h_sat - b_sat == 2 * yon and tahta[b_sat + yon][b_sut] == ' ': return True
        if df_sut == 1 and h_sat - b_sat == yon and hedef != ' ': return True
        if df_sut == 1 and h_sat - b_sat == yon and hedef == ' ' and oda['gecerken'] == (h_sat, h_sut): return True
        return False
    elif tip == 'R':
        return (b_sat == h_sat or b_sut == h_sut) and yol_acik_mi(tahta, b_sat, b_sut, h_sat, h_sut)
    elif tip == 'B':
        return (df_sat == df_sut) and yol_acik_mi(tahta, b_sat, b_sut, h_sat, h_sut)
    elif tip == 'Q':
        return (b_sat == h_sat or b_sut == h_sut or df_sat == df_sut) and yol_acik_mi(tahta, b_sat, b_sut, h_sat, h_sut)
    elif tip == 'N':
        return (df_sat == 2 and df_sut == 1) or (df_sat == 1 and df_sut == 2)
    elif tip == 'K':
        if df_sat <= 1 and df_sut <= 1: return True
        if df_sat == 0 and df_sut == 2:
            if beyaz_mi and (b_sat, b_sut) == (7, 4):
                if oda['b_sah'] or tehdit_altinda_mi(tahta, 7, 4, False): return False
                if h_sut == 6:
                    if oda['b_k_sag'] or tahta[7][7] != 'R': return False
                    if tahta[7][5] != ' ' or tahta[7][6] != ' ': return False
                    if tehdit_altinda_mi(tahta, 7, 5, False) or tehdit_altinda_mi(tahta, 7, 6, False): return False
                    return True
                elif h_sut == 2:
                    if oda['b_k_sol'] or tahta[7][0] != 'R': return False
                    if tahta[7][1] != ' ' or tahta[7][2] != ' ' or tahta[7][3] != ' ': return False
                    if tehdit_altinda_mi(tahta, 7, 3, False) or tehdit_altinda_mi(tahta, 7, 2, False): return False
                    return True
            elif not beyaz_mi and (b_sat, b_sut) == (0, 4):
                if oda['s_sah'] or tehdit_altinda_mi(tahta, 0, 4, True): return False
                if h_sut == 6:
                    if oda['s_k_sag'] or tahta[0][7] != 'r': return False
                    if tahta[0][5] != ' ' or tahta[0][6] != ' ': return False
                    if tehdit_altinda_mi(tahta, 0, 5, True) or tehdit_altinda_mi(tahta, 0, 6, True): return False
                    return True
                elif h_sut == 2:
                    if oda['s_k_sol'] or tahta[0][0] != 'r': return False
                    if tahta[0][1] != ' ' or tahta[0][2] != ' ' or tahta[0][3] != ' ': return False
                    if tehdit_altinda_mi(tahta, 0, 3, True) or tehdit_altinda_mi(tahta, 0, 2, True): return False
                    return True
        return False
    return False

def gecerli_hamleleri_bul(oda, b_sat, b_sut, b_sirasi):
    tahta = oda['tahta']
    secilen = tahta[b_sat][b_sut]
    # Sadece sırası gelen tarafın kendi taşı oynatılabilir
    if secilen == ' ' or secilen.isupper() != b_sirasi:
        return []
    hamleler = []
    for h_sat in range(8):
        for h_sut in range(8):
            hedef = tahta[h_sat][h_sut]
            if hedef == ' ' or (hedef.isupper() != b_sirasi):
                if kural_kontrol(oda, secilen, b_sat, b_sut, h_sat, h_sut):
                    alinan_ep = ' '
                    ep = False
                    yon = -1 if b_sirasi else 1
                    if secilen.upper() == 'P' and abs(h_sut - b_sut) == 1 and hedef == ' ':
                        ep = True
                        alinan_ep = tahta[h_sat - yon][h_sut]
                        tahta[h_sat - yon][h_sut] = ' '
                    tahta[h_sat][h_sut] = secilen
                    tahta[b_sat][b_sut] = ' '
                    roklu = False
                    if secilen.upper() == 'K' and abs(h_sut - b_sut) == 2:
                        roklu = True
                        k_eski, k_yeni = ((h_sat, 7), (h_sat, 5)) if h_sut == 6 else ((h_sat, 0), (h_sat, 3))
                        tahta[k_yeni[0]][k_yeni[1]] = tahta[k_eski[0]][k_eski[1]]
                        tahta[k_eski[0]][k_eski[1]] = ' '

                    s_sat, s_sut = sah_konumu_bul(tahta, b_sirasi)
                    if s_sat == -1 or not tehdit_altinda_mi(tahta, s_sat, s_sut, not b_sirasi):
                        hamleler.append([h_sat, h_sut])

                    if roklu:
                        tahta[k_eski[0]][k_eski[1]] = tahta[k_yeni[0]][k_yeni[1]]
                        tahta[k_yeni[0]][k_yeni[1]] = ' '
                    if ep:
                        tahta[h_sat - yon][h_sut] = alinan_ep
                    tahta[b_sat][b_sut] = secilen
                    tahta[h_sat][h_sut] = hedef
    return hamleler

def tum_gecerli_hamleler_sayisi(oda, b_sirasi):
    tahta = oda['tahta']
    return sum(len(gecerli_hamleleri_bul(oda, r, c, b_sirasi)) for r in range(8) for c in range(8) if tahta[r][c] != ' ' and tahta[r][c].isupper() == b_sirasi)

def yetersiz_materyal_mi(tahta):
    taslar = []
    fil_renkleri = []
    for r in range(8):
        for c in range(8):
            t = tahta[r][c]
            if t != ' ' and t.upper() != 'K':
                taslar.append(t.upper())
                if t.upper() == 'B':
                    fil_renkleri.append((r + c) % 2)
    if len(taslar) == 0: return True
    if len(taslar) == 1 and taslar[0] in ['N', 'B']: return True
    # Tüm filler aynı renk karedeyse (başka taş yoksa) mat imkansızdır
    if taslar and all(t == 'B' for t in taslar) and len(set(fil_renkleri)) == 1: return True
    return False

# =====================================================================
# 4. HAMLE UYGULAMA VE YAPAY ZEKA (BOT)
# =====================================================================
ROK_ANAHTARLARI = ('b_sah', 'b_k_sol', 'b_k_sag', 's_sah', 's_k_sol', 's_k_sag')

def hamle_uygula(d, b_sat, b_sut, h_sat, h_sut, terfi=None):
    """Hamleyi d['tahta'] üzerinde yapar, rok/geçerken bilgilerini günceller.
    Dönüş: (alinan_tas veya None, ek_hamleler[rok kalesi gibi])"""
    tahta = d['tahta']
    secilen = tahta[b_sat][b_sut]
    hedef = tahta[h_sat][h_sut]
    beyaz = secilen.isupper()
    alinan = hedef if hedef != ' ' else None
    ek = []

    yeni_ep = None
    if secilen.upper() == 'P':
        yon = -1 if beyaz else 1
        if abs(h_sat - b_sat) == 2:
            yeni_ep = (b_sat + yon, b_sut)
        if b_sut != h_sut and hedef == ' ':  # geçerken alma
            alinan = tahta[h_sat - yon][h_sut]
            tahta[h_sat - yon][h_sut] = ' '
    d['gecerken'] = yeni_ep

    # Köşedeki kale yenirse o tarafın rok hakkı gider
    if hedef == 'R':
        if (h_sat, h_sut) == (7, 0): d['b_k_sol'] = True
        elif (h_sat, h_sut) == (7, 7): d['b_k_sag'] = True
    elif hedef == 'r':
        if (h_sat, h_sut) == (0, 0): d['s_k_sol'] = True
        elif (h_sat, h_sut) == (0, 7): d['s_k_sag'] = True

    if secilen.upper() == 'K' and abs(h_sut - b_sut) == 2:
        if h_sut == 6:
            tahta[h_sat][5] = tahta[h_sat][7]; tahta[h_sat][7] = ' '
            ek.append([[h_sat, 7], [h_sat, 5]])
        else:
            tahta[h_sat][3] = tahta[h_sat][0]; tahta[h_sat][0] = ' '
            ek.append([[h_sat, 0], [h_sat, 3]])

    if secilen.upper() == 'P' and h_sat in (0, 7):
        secim = str(terfi).upper() if terfi else 'Q'
        if secim not in ('Q', 'R', 'B', 'N'):
            secim = 'Q'
        tahta[h_sat][h_sut] = secim if beyaz else secim.lower()
    else:
        tahta[h_sat][h_sut] = secilen
    tahta[b_sat][b_sut] = ' '

    if secilen == 'K': d['b_sah'] = True
    elif secilen == 'k': d['s_sah'] = True
    elif secilen == 'R':
        if (b_sat, b_sut) == (7, 0): d['b_k_sol'] = True
        elif (b_sat, b_sut) == (7, 7): d['b_k_sag'] = True
    elif secilen == 'r':
        if (b_sat, b_sut) == (0, 0): d['s_k_sol'] = True
        elif (b_sat, b_sut) == (0, 7): d['s_k_sag'] = True

    return alinan, ek

def durum_kopyala(d):
    k = {'tahta': [s[:] for s in d['tahta']], 'gecerken': d['gecerken']}
    for a in ROK_ANAHTARLARI:
        k[a] = d[a]
    return k

def tum_hamleler(d, beyaz):
    tahta = d['tahta']
    hamleler = []
    for r in range(8):
        for c in range(8):
            t = tahta[r][c]
            if t != ' ' and t.isupper() == beyaz:
                for h in gecerli_hamleleri_bul(d, r, c, beyaz):
                    hamleler.append((r, c, h[0], h[1]))
    return hamleler

DEGERLER = {'P': 100, 'N': 320, 'B': 330, 'R': 500, 'Q': 900, 'K': 0}
# Beyaz açısından konum tabloları (satır 0 = 8. sıra)
PST = {
    'P': [[0]*8, [50]*8, [10,10,20,30,30,20,10,10], [5,5,10,25,25,10,5,5],
          [0,0,0,20,20,0,0,0], [5,-5,-10,0,0,-10,-5,5], [5,10,10,-20,-20,10,10,5], [0]*8],
    'N': [[-50,-40,-30,-30,-30,-30,-40,-50], [-40,-20,0,0,0,0,-20,-40], [-30,0,10,15,15,10,0,-30],
          [-30,5,15,20,20,15,5,-30], [-30,0,15,20,20,15,0,-30], [-30,5,10,15,15,10,5,-30],
          [-40,-20,0,5,5,0,-20,-40], [-50,-40,-30,-30,-30,-30,-40,-50]],
    'B': [[-20,-10,-10,-10,-10,-10,-10,-20], [-10,0,0,0,0,0,0,-10], [-10,0,5,10,10,5,0,-10],
          [-10,5,5,10,10,5,5,-10], [-10,0,10,10,10,10,0,-10], [-10,10,10,10,10,10,10,-10],
          [-10,5,0,0,0,0,5,-10], [-20,-10,-10,-10,-10,-10,-10,-20]],
    'R': [[0]*8, [5,10,10,10,10,10,10,5]] + [[-5,0,0,0,0,0,0,-5]]*5 + [[0,0,0,5,5,0,0,0]],
    'Q': [[-20,-10,-10,-5,-5,-10,-10,-20], [-10,0,0,0,0,0,0,-10], [-10,0,5,5,5,5,0,-10],
          [-5,0,5,5,5,5,0,-5], [0,0,5,5,5,5,0,-5], [-10,5,5,5,5,5,0,-10],
          [-10,0,5,0,0,0,0,-10], [-20,-10,-10,-5,-5,-10,-10,-20]],
    'K': [[-30,-40,-40,-50,-50,-40,-40,-30]]*4 + [[-20,-30,-30,-40,-40,-30,-30,-20],
          [-10,-20,-20,-20,-20,-20,-20,-10], [20,20,0,0,0,0,20,20], [20,30,10,0,0,10,30,20]],
}

def degerlendir(tahta):
    """Pozitif = beyaz önde."""
    skor = 0
    for r in range(8):
        for c in range(8):
            t = tahta[r][c]
            if t == ' ':
                continue
            tip = t.upper()
            if t.isupper():
                skor += DEGERLER[tip] + PST[tip][r][c]
            else:
                skor -= DEGERLER[tip] + PST[tip][7 - r][c]
    return skor

class SureDoldu(Exception):
    pass

MAT_SKORU = 100000

def _sirala(d, hamleler):
    tahta = d['tahta']
    def anahtar(m):
        hedef = tahta[m[2]][m[3]]
        return -(DEGERLER.get(hedef.upper(), 0) * 10 - DEGERLER[tahta[m[0]][m[1]].upper()] // 10) if hedef != ' ' else 0
    return sorted(hamleler, key=anahtar)

def negamax(d, beyaz, derinlik, alpha, beta, ply, bitis):
    if time.time() > bitis:
        raise SureDoldu()
    if derinlik == 0:
        return degerlendir(d['tahta']) * (1 if beyaz else -1)
    hamleler = tum_hamleler(d, beyaz)
    if not hamleler:
        r, c = sah_konumu_bul(d['tahta'], beyaz)
        if r != -1 and tehdit_altinda_mi(d['tahta'], r, c, not beyaz):
            return -MAT_SKORU + ply
        return 0
    en_iyi = -MAT_SKORU * 2
    for m in _sirala(d, hamleler):
        k = durum_kopyala(d)
        hamle_uygula(k, *m)
        skor = -negamax(k, not beyaz, derinlik - 1, -beta, -alpha, ply + 1, bitis)
        if skor > en_iyi:
            en_iyi = skor
        if skor > alpha:
            alpha = skor
        if alpha >= beta:
            break
    return en_iyi

def bot_hamlesi_sec(d, beyaz, zorluk, kalan_sure=None):
    hamleler = tum_hamleler(d, beyaz)
    if not hamleler:
        return None
    if zorluk == 'kolay':
        # Çoğunlukla rastgele, bazen bedava taşı alır
        if random.random() < 0.35:
            tahta = d['tahta']
            alanlar = [m for m in hamleler if tahta[m[2]][m[3]] != ' ']
            if alanlar:
                return max(alanlar, key=lambda m: DEGERLER[tahta[m[2]][m[3]].upper()])
        return random.choice(hamleler)

    maks_derinlik, sure_limit = (2, 1.5) if zorluk == 'orta' else (4, 2.5)
    if kalan_sure is not None:
        # Kalan sürenin en fazla ~1/30'unu harca; kısa oyunlarda süreden kaybetmesin
        sure_limit = max(0.2, min(sure_limit, kalan_sure / 30))
    bitis = time.time() + sure_limit
    random.shuffle(hamleler)  # aynı oyunu hep aynı oynamasın
    en_iyi = hamleler[0]
    for derinlik in range(1, maks_derinlik + 1):
        try:
            alpha = -MAT_SKORU * 2
            bu_tur_en_iyi = None
            for m in _sirala(d, hamleler):
                k = durum_kopyala(d)
                hamle_uygula(k, *m)
                skor = -negamax(k, not beyaz, derinlik - 1, -MAT_SKORU * 2, -alpha, 1, bitis)
                if skor > alpha or bu_tur_en_iyi is None:
                    alpha = skor
                    bu_tur_en_iyi = m
            en_iyi = bu_tur_en_iyi
            # En iyi hamleyi bir sonraki derinlikte ilk dene
            hamleler.remove(en_iyi); hamleler.insert(0, en_iyi)
            if alpha >= MAT_SKORU - 100:
                break
        except SureDoldu:
            break
    return en_iyi

# =====================================================================
# 5. HTML ARAYÜZ
# =====================================================================
HTML_PAGE = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="google-site-verification" content="lIdhFOFea-Gne9dwQpDCUbceGuTWtpOVv-SRFOeaw-o" />
    <title>Goaltech Chess Online</title>
    <link href="https://fonts.googleapis.com/css2?family=Anton&family=Outfit:wght@400;600;700;800&family=JetBrains+Mono:wght@600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --card-bg: rgba(20, 16, 44, 0.62);
            --card-border: rgba(255, 255, 255, 0.10);
            --primary: #8b5cf6;
            --primary-2: #6366f1;
            --accent: #22d3ee;
            --gold: #fbbf24;
            --sq-light: #ece6ff;
            --sq-dark: #8a7fc4;
        }
        * { box-sizing: border-box; font-family: 'Outfit', sans-serif; }
        body {
            color: #fff; margin: 0; padding: 0; min-height: 100vh; overflow-x: hidden;
            background: linear-gradient(-45deg, #1a0b3d, #2d1065, #0c2d5a, #083d4a, #1a0b3d);
            background-size: 400% 400%;
            animation: bgShift 22s ease infinite;
        }
        @keyframes bgShift {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }

        /* Yüzen arka plan taşları ve ışık küreleri */
        #bg-layer { position: fixed; inset: 0; pointer-events: none; z-index: 0; overflow: hidden; }
        .orb { position: absolute; border-radius: 50%; filter: blur(70px); opacity: 0.45; animation: orbMove 18s ease-in-out infinite alternate; }
        .orb.o1 { width: 380px; height: 380px; background: #7c3aed; top: -100px; left: -80px; }
        .orb.o2 { width: 320px; height: 320px; background: #06b6d4; bottom: -120px; right: -60px; animation-delay: -6s; }
        .orb.o3 { width: 260px; height: 260px; background: #db2777; top: 40%; left: 60%; opacity: 0.25; animation-delay: -12s; }
        @keyframes orbMove { 0% { transform: translate(0,0) scale(1); } 100% { transform: translate(60px, 40px) scale(1.15); } }
        .float-piece { position: absolute; bottom: -80px; color: rgba(255,255,255,0.07); user-select: none; animation: floatUp linear infinite; }
        @keyframes floatUp {
            0% { transform: translateY(0) rotate(0deg); opacity: 0; }
            10% { opacity: 1; }
            90% { opacity: 1; }
            100% { transform: translateY(-115vh) rotate(360deg); opacity: 0; }
        }

        /* ===== GİRİŞ EKRANI ===== */
        #welcome-screen { position: fixed; inset: 0; z-index: 100; overflow-y: auto; background: #262522; display: flex; justify-content: center; align-items: flex-start; padding: 32px 16px; }
        .hero { width: 100%; max-width: 1180px; display: flex; flex-direction: column; gap: 18px; margin: auto 0; }
        .hero-banner { display: grid; grid-template-columns: 1fr 1.1fr; background: #2f2e2b; border-radius: 28px; overflow: hidden; box-shadow: 0 24px 60px rgba(0,0,0,0.45); animation: popIn 0.6s cubic-bezier(.2,1.2,.4,1) both; }
        .hero-left { position: relative; display: flex; flex-direction: column; align-items: center; justify-content: space-between; padding: 40px 24px 0; min-height: 100%; }
        .hero-title { margin: 0; font-family: 'Anton', 'Impact', 'Arial Narrow', sans-serif; font-weight: 400; font-size: clamp(50px, 7.2vw, 108px); line-height: 1.02; letter-spacing: 1px; text-align: center; color: #81b64c; text-shadow: 0 6px 0 #4b7a2b, 0 14px 24px rgba(0,0,0,0.45); }
        .hero-title span { display: block; animation: titleIn 0.7s cubic-bezier(.2,1.3,.4,1) both; }
        .hero-title span:nth-child(2) { animation-delay: 0.12s; }
        @keyframes titleIn { from { opacity: 0; transform: translateY(30px) scale(0.9); } to { opacity: 1; transform: none; } }
        .hero-art { position: relative; width: 100%; height: clamp(170px, 20vw, 260px); display: flex; align-items: flex-end; justify-content: center; }
        .hero-floor { position: absolute; left: -10%; right: -10%; bottom: -40px; height: 70%; background-color: #2a2927; background-image: conic-gradient(#383734 25%, transparent 0 50%, #383734 0 75%, transparent 0); background-size: 25% 25%; transform: perspective(380px) rotateX(58deg); transform-origin: bottom; opacity: 0.9; -webkit-mask-image: linear-gradient(to top, #000 30%, transparent); mask-image: linear-gradient(to top, #000 30%, transparent); }
        .art { position: absolute; bottom: 0; line-height: 0.85; font-family: 'Segoe UI Symbol', 'DejaVu Sans', serif; user-select: none; }
        .art-knight { left: 12%; font-size: clamp(100px, 12vw, 185px); color: #5b5a57; transform: scaleX(-1); filter: drop-shadow(0 10px 14px rgba(0,0,0,0.5)); animation: artBob 4s ease-in-out infinite; }
        .art-rook { right: 12%; font-size: clamp(90px, 11vw, 165px); color: #6a6966; filter: drop-shadow(0 10px 14px rgba(0,0,0,0.5)); animation: artBob 4s ease-in-out -2s infinite; }
        .art-pawn { left: 50%; font-size: clamp(140px, 16vw, 250px); color: #81b64c; z-index: 2; transform: translateX(-50%); text-shadow: inset 0 0 0 #000; filter: drop-shadow(0 16px 18px rgba(0,0,0,0.55)) drop-shadow(-6px -4px 0 rgba(255,255,255,0.08)); animation: pawnBob 3s ease-in-out infinite; }
        @keyframes artBob { 0%,100% { margin-bottom: 0; } 50% { margin-bottom: 8px; } }
        @keyframes pawnBob { 0%,100% { transform: translateX(-50%) translateY(0); } 50% { transform: translateX(-50%) translateY(-12px); } }
        .hero-right { display: flex; align-items: center; justify-content: center; padding: 28px; background: linear-gradient(135deg, rgba(139,92,246,0.18), rgba(34,211,238,0.12)); }
        .hero-board-frame { padding: 10px; border-radius: 18px; background: linear-gradient(135deg, rgba(139,92,246,0.75), rgba(34,211,238,0.6)); box-shadow: 0 20px 50px rgba(0,0,0,0.5); animation: boardIn 0.8s cubic-bezier(.2,1.2,.4,1) 0.15s both; }
        @keyframes boardIn { from { opacity: 0; transform: translateX(40px) rotate(3deg); } to { opacity: 1; transform: none; } }
        .hero-board { --hb: min(440px, 34vw); width: var(--hb); height: var(--hb); display: grid; grid-template-columns: repeat(8, 1fr); grid-template-rows: repeat(8, 1fr); border-radius: 8px; overflow: hidden; }
        .hb-sq { position: relative; display: flex; align-items: center; justify-content: center; font-size: calc(var(--hb) / 8 * 0.74); line-height: 1; font-family: 'Segoe UI Symbol', 'DejaVu Sans', serif; }
        .hb-sq.light { background: var(--sq-light); } .hb-sq.dark { background: var(--sq-dark); }
        .hb-sq .w { color: #fff; text-shadow: 0 0 2px #1e1b4b, 0 0 2px #1e1b4b, 0 3px 4px rgba(0,0,0,0.4); }
        .hb-sq .b { color: #1e1b2e; text-shadow: 0 0 2px rgba(255,255,255,0.6), 0 3px 4px rgba(0,0,0,0.35); }
        .hb-sq .w, .hb-sq .b { animation: pieceDrop 0.45s cubic-bezier(.2,1.4,.4,1) both; }
        @keyframes pieceDrop { from { opacity: 0; transform: translateY(-30px); } to { opacity: 1; transform: none; } }
        .hb-coord { position: absolute; font: 700 calc(var(--hb) / 8 * 0.17) 'Outfit', sans-serif; }
        .hb-coord.rank { top: 3px; left: 4px; } .hb-coord.file { bottom: 2px; right: 4px; }
        .hb-sq.light .hb-coord { color: var(--sq-dark); } .hb-sq.dark .hb-coord { color: var(--sq-light); }

        .hero-panel { background: #2f2e2b; border-radius: 24px; padding: 22px; box-shadow: 0 16px 40px rgba(0,0,0,0.35); animation: slideIn 0.6s ease 0.25s both; }
        .hero-panel .input-group label { color: #a3a29f; }
        .hero-panel .input-group input { background: #1f1e1c; border-color: #403f3c; font-size: 16px; }
        .hero-panel .input-group input:focus { border-color: #81b64c; box-shadow: 0 0 0 3px rgba(129,182,76,0.3); }
        @keyframes knightHop { 0%,100% { transform: translateY(0) rotate(0); } 30% { transform: translateY(-14px) rotate(-8deg); } 60% { transform: translateY(0) rotate(4deg); } }
        @keyframes shine { to { background-position: 300% 0; } }
        @keyframes popIn { from { opacity: 0; transform: scale(0.85) translateY(20px); } to { opacity: 1; transform: none; } }
        .input-group { margin-bottom: 14px; text-align: left; }
        .input-group label { display: block; font-size: 11px; font-weight: 700; color: #a5b4fc; text-transform: uppercase; margin-bottom: 6px; letter-spacing: 0.5px; }
        .input-group input { width: 100%; padding: 12px 14px; border-radius: 12px; border: 1px solid var(--card-border); background: rgba(10, 6, 30, 0.55); color: #fff; font-size: 15px; outline: none; transition: 0.2s; }
        .input-group input:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(139, 92, 246, 0.3); }
        .btn-main { width: 100%; padding: 13px; background: linear-gradient(135deg, var(--primary), var(--primary-2)); border: none; border-radius: 12px; color: #fff; font-size: 15px; font-weight: 700; cursor: pointer; transition: 0.2s; box-shadow: 0 10px 24px rgba(124, 58, 237, 0.45); margin-top: 8px; }
        .btn-main:hover { transform: translateY(-2px); box-shadow: 0 14px 30px rgba(124, 58, 237, 0.6); }
        .btn-main:active { transform: translateY(0) scale(0.98); }

        #game-screen { display: none; flex-direction: column; align-items: center; padding: 16px; max-width: 600px; margin: 0 auto; position: relative; z-index: 1; }
        #game-screen > * { animation: slideIn 0.5s ease both; }
        #game-screen > *:nth-child(2) { animation-delay: 0.05s; }
        #game-screen > *:nth-child(3) { animation-delay: 0.1s; }
        #game-screen > *:nth-child(4) { animation-delay: 0.15s; }
        #game-screen > *:nth-child(5) { animation-delay: 0.2s; }
        #game-screen > *:nth-child(6) { animation-delay: 0.25s; }
        @keyframes slideIn { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: none; } }

        .top-bar { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 8px; margin-bottom: 10px; background: var(--card-bg); padding: 10px 16px; border-radius: 16px; border: 1px solid var(--card-border); backdrop-filter: blur(12px); }
        .logo-title { font-size: 20px; font-weight: 800; letter-spacing: -0.5px; white-space: nowrap; }
        .logo-title span { color: var(--accent); }
        .role-badge { font-size: 12px; padding: 4px 10px; border-radius: 20px; font-weight: 700; background: rgba(255,255,255,0.08); border: 1px solid var(--card-border); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

        .time-picker-bar { width: 100%; display: flex; align-items: center; justify-content: space-between; gap: 8px; background: var(--card-bg); border: 1px solid var(--card-border); padding: 8px 14px; border-radius: 14px; margin-bottom: 12px; backdrop-filter: blur(12px); transition: opacity 0.3s; }
        .time-picker-bar.locked { opacity: 0.5; }
        .time-picker-bar.locked .time-btn { cursor: not-allowed; }
        .time-label { font-size: 12px; font-weight: 700; color: #a5b4fc; text-transform: uppercase; }
        .time-options { display: flex; gap: 6px; }
        .time-btn { background: rgba(255,255,255,0.06); border: 1px solid var(--card-border); color: #e0e7ff; padding: 6px 12px; border-radius: 8px; font-size: 12px; font-weight: 700; cursor: pointer; transition: 0.2s; }
        .time-btn:hover { background: rgba(255,255,255,0.16); }
        .time-btn.active { background: var(--primary); color: white; border-color: var(--primary); box-shadow: 0 0 14px rgba(139,92,246,0.6); }

        .status-container { width: 100%; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
        .score-card { background: var(--card-bg); border: 1px solid var(--card-border); padding: 12px; border-radius: 14px; display: flex; flex-direction: column; justify-content: space-between; transition: 0.35s; backdrop-filter: blur(12px); }
        .score-card.active-turn { border-color: var(--gold); box-shadow: 0 0 22px rgba(251, 191, 36, 0.3); animation: turnGlow 1.8s ease-in-out infinite; }
        @keyframes turnGlow { 0%,100% { box-shadow: 0 0 10px rgba(251,191,36,0.2); } 50% { box-shadow: 0 0 26px rgba(251,191,36,0.45); } }
        .card-header { display: flex; justify-content: space-between; align-items: center; gap: 6px; }
        .score-card .title { font-size: 12px; font-weight: 700; color: #c7d2fe; text-transform: uppercase; }
        .score-num { display: inline-block; }
        .score-num.bump { animation: bump 0.5s ease; }
        @keyframes bump { 0% { transform: scale(1); } 40% { transform: scale(1.6); color: var(--gold); } 100% { transform: scale(1); } }
        .clock-display { font-family: 'JetBrains Mono', monospace; font-size: 22px; font-weight: 700; color: #f8fafc; }
        .clock-display.danger { color: #f87171; animation: blink 1s steps(2) infinite; }
        @keyframes blink { 50% { opacity: 0.45; } }
        .caps { font-size: 16px; min-height: 20px; color: #c4b5fd; margin-top: 4px; word-break: break-all; }

        .board-wrapper { position: relative; padding: 6px; background: linear-gradient(135deg, rgba(139,92,246,0.5), rgba(34,211,238,0.4)); border-radius: 16px; box-shadow: 0 20px 50px rgba(0,0,0,0.55), 0 0 40px rgba(139,92,246,0.25); transition: 0.3s; }
        .board-wrapper.waiting { pointer-events: none; }
        .board-wrapper.waiting .board { filter: grayscale(0.8) brightness(0.55); }
        .waiting-overlay { display: none; position: absolute; inset: 0; align-items: center; justify-content: center; z-index: 50; flex-direction: column; text-align: center; padding: 12px; }
        .board-wrapper.waiting .waiting-overlay { display: flex; }
        .wait-text { font-size: 18px; font-weight: 800; color: #fff; background: rgba(15, 10, 40, 0.92); padding: 12px 20px; border-radius: 12px; border: 1px solid var(--primary); animation: waitPulse 1.6s ease-in-out infinite; }
        @keyframes waitPulse { 0%,100% { box-shadow: 0 0 12px rgba(139,92,246,0.4); } 50% { box-shadow: 0 0 32px rgba(139,92,246,0.9); } }
        .wait-sub { display: block; font-size: 12px; color: #c7d2fe; font-weight: 600; margin-top: 6px; }

        .board { display: grid; grid-template-columns: repeat(8, 62px); grid-template-rows: repeat(8, 62px); border-radius: 10px; overflow: hidden; transition: filter 0.3s; }
        @media (max-width: 560px) {
            .board { grid-template-columns: repeat(8, calc((100vw - 48px) / 8)); grid-template-rows: repeat(8, calc((100vw - 48px) / 8)); }
            .square img { width: 80% !important; height: 80% !important; }
            .glyph { font-size: calc((100vw - 48px) / 8 * 0.72); }
            .time-label { display: none; }
            .action-grid { gap: 8px !important; grid-template-columns: repeat(2, 1fr) !important; }
            .mode-selection { flex-direction: column; }
            .hero-banner { grid-template-columns: 1fr; }
            .hero-left { padding-top: 26px; }
            .hero-art { height: 140px; }
            .hero-right { padding: 16px; }
            .hero-board { --hb: min(calc(100vw - 84px), 260px); }
            #welcome-screen { padding: 16px; }
            .btn-modern { padding: 12px 8px !important; }
        }
        .square { display: flex; align-items: center; justify-content: center; cursor: pointer; position: relative; user-select: none; -webkit-tap-highlight-color: transparent; transition: background-color 0.25s; }
        .square img { width: 48px; height: 48px; pointer-events: none; position: relative; z-index: 5; filter: drop-shadow(0 4px 4px rgba(0,0,0,0.35)); transition: transform 0.15s; }
        .glyph { position: relative; z-index: 5; font-size: 46px; line-height: 1; pointer-events: none; transition: transform 0.15s; font-family: 'Segoe UI Symbol', 'DejaVu Sans', serif; }
        .glyph-w { color: #fff; text-shadow: 0 0 2px #1e1b4b, 0 0 2px #1e1b4b, 0 3px 4px rgba(0,0,0,0.4); }
        .glyph-b { color: #1e1b2e; text-shadow: 0 0 2px rgba(255,255,255,0.6), 0 3px 4px rgba(0,0,0,0.35); }
        .promo-piece .glyph { font-size: 44px; display: block; width: 48px; text-align: center; }
        .square:hover .piece { transform: translateY(-2px) scale(1.06); }
        .light { background-color: var(--sq-light); }
        .dark { background-color: var(--sq-dark); }
        .last-move::before { content: ''; position: absolute; inset: 0; background: rgba(45, 212, 191, 0.42); pointer-events: none; }
        .selected { background-color: #fde047 !important; }
        .selected .piece { animation: lift 0.9s ease-in-out infinite alternate; }
        @keyframes lift { from { transform: translateY(0) scale(1.05); } to { transform: translateY(-5px) scale(1.12); } }
        .in-check { background: radial-gradient(circle, #ef4444 0%, #b91c1c 70%) !important; animation: checkPulse 1s ease-in-out infinite; }
        @keyframes checkPulse { 0%,100% { box-shadow: inset 0 0 0 0 rgba(255,255,255,0); } 50% { box-shadow: inset 0 0 18px 4px rgba(255,255,255,0.55); } }
        .valid-dot { width: 30%; height: 30%; background-color: rgba(34, 197, 94, 0.85); border-radius: 50%; position: absolute; z-index: 10; pointer-events: none; animation: dotIn 0.25s ease both, dotPulse 1.4s ease-in-out 0.25s infinite; }
        .valid-ring { position: absolute; inset: 6%; border: 4px solid rgba(34, 197, 94, 0.85); border-radius: 50%; z-index: 10; pointer-events: none; animation: dotIn 0.25s ease both; }
        @keyframes dotIn { from { transform: scale(0); opacity: 0; } to { transform: scale(1); opacity: 1; } }
        @keyframes dotPulse { 0%,100% { transform: scale(1); } 50% { transform: scale(1.25); } }
        .capture-burst { position: absolute; inset: 0; z-index: 20; pointer-events: none; border-radius: 50%; animation: burst 0.55s ease-out forwards; background: radial-gradient(circle, rgba(251,191,36,0.9) 0%, rgba(244,63,94,0.6) 40%, transparent 70%); }
        @keyframes burst { from { transform: scale(0.2); opacity: 1; } to { transform: scale(1.8); opacity: 0; } }
        .board.shake { animation: shake 0.4s ease; }
        @keyframes shake { 0%,100% { transform: translateX(0); } 20% { transform: translateX(-6px); } 40% { transform: translateX(6px); } 60% { transform: translateX(-4px); } 80% { transform: translateX(4px); } }

        .action-grid { width: 100%; display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 12px; }
        .action-grid.three { grid-template-columns: repeat(3, 1fr); }
        .btn-new { background: rgba(251, 191, 36, 0.16); color: #fde68a; }
        .btn-modern { padding: 12px 14px; border-radius: 12px; border: 1px solid var(--card-border); background: var(--card-bg); color: #fff; font-size: 13px; font-weight: 700; cursor: pointer; transition: 0.2s; display: flex; align-items: center; justify-content: center; gap: 6px; backdrop-filter: blur(12px); }
        .btn-modern:hover { transform: translateY(-2px); filter: brightness(1.2); }
        .btn-modern:active { transform: scale(0.96); }
        .btn-share { background: linear-gradient(135deg, rgba(34, 211, 238, 0.22), rgba(8, 145, 178, 0.22)); border-color: var(--accent); color: #67e8f9; }
        .btn-undo { background: rgba(139, 92, 246, 0.2); color: #c4b5fd; }
        .btn-logout { background: rgba(239, 68, 68, 0.18); color: #fca5a5; }

        #msg { margin-top: 10px; font-size: 15px; font-weight: 700; color: #fca5a5; min-height: 22px; text-align: center; transition: color 0.3s; }
        #msg.info { color: #a5f3fc; }
        #msg.my-turn { color: #fde68a; animation: fadePulse 2s ease-in-out infinite; }
        @keyframes fadePulse { 0%,100% { opacity: 1; } 50% { opacity: 0.6; } }

        #toast { position: fixed; bottom: 30px; left: 50%; transform: translateX(-50%); background: linear-gradient(135deg, #06b6d4, #8b5cf6); color: white; padding: 10px 20px; border-radius: 30px; font-weight: 700; font-size: 13px; opacity: 0; pointer-events: none; transition: 0.3s; z-index: 300; }
        #toast.show { opacity: 1; transform: translate(-50%, -10px); }

        .modal { display: none; position: fixed; inset: 0; background: rgba(5,2,20,0.65); backdrop-filter: blur(8px); z-index: 200; align-items: center; justify-content: center; padding: 16px; }
        .modal.open { display: flex; }
        .modal-content { background: rgba(28, 20, 60, 0.92); border: 1px solid var(--card-border); padding: 24px; border-radius: 20px; text-align: center; animation: popIn 0.4s cubic-bezier(.2,1.3,.4,1) both; max-width: 100%; }
        .promo-pieces { display: flex; gap: 12px; margin-top: 16px; flex-wrap: wrap; justify-content: center; }
        .promo-piece { background: rgba(255,255,255,0.06); padding: 10px; border-radius: 12px; cursor: pointer; transition: 0.2s; border: 1px solid var(--card-border); }
        .promo-piece:hover { background: rgba(139,92,246,0.35); transform: scale(1.12) rotate(-4deg); }
        .promo-piece img { width: 48px; height: 48px; display: block; }
        .gameover-icon { font-size: 58px; display: inline-block; animation: trophy 1.2s ease-in-out infinite alternate; }
        @keyframes trophy { from { transform: rotate(-8deg) scale(1); } to { transform: rotate(8deg) scale(1.12); } }
        .gameover-title { font-size: 22px; font-weight: 800; margin: 8px 0 18px; }
        .modal-actions { display: flex; gap: 10px; justify-content: center; }
        .modal-actions .btn-main { width: auto; padding: 11px 20px; margin: 0; }
        .btn-ghost { background: rgba(255,255,255,0.08); border: 1px solid var(--card-border); color: #fff; border-radius: 12px; padding: 11px 20px; font-weight: 700; cursor: pointer; }

        .confetti { position: fixed; top: -12px; width: 10px; height: 14px; z-index: 250; pointer-events: none; animation: confettiFall linear forwards; }
        @keyframes confettiFall { to { transform: translateY(110vh) rotate(720deg); } }


        /* Mod seçimi */
        .mode-selection { display: flex; gap: 16px; }
        .mode-card { flex: 1; background: #262522; border: 1px solid #3d3c39; border-radius: 18px; padding: 18px 16px; display: flex; flex-direction: column; justify-content: space-between; gap: 12px; transition: 0.25s; text-align: center; }
        .mode-card:hover { transform: translateY(-4px); border-color: #81b64c; box-shadow: 0 12px 30px rgba(0,0,0,0.4); }
        .mode-icon { font-size: 40px; display: inline-block; animation: knightHop 3s ease-in-out infinite; }
        .mode-card.friend .mode-icon { animation-delay: -1.5s; }
        .mode-card h3 { margin: 4px 0 0; font-size: 18px; color: #fff; }
        .mode-card p { margin: 2px 0 0; font-size: 13px; color: #a3a29f; }
        .level-picker { display: flex; gap: 6px; }
        .level-btn { flex: 1; padding: 9px 4px; border-radius: 10px; border: 1px solid #403f3c; background: #1f1e1c; color: #d6d5d2; font-weight: 700; font-size: 13px; cursor: pointer; transition: 0.2s; }
        .level-btn:hover { background: #343330; }
        .level-btn.active { background: #4b7a2b; border-color: #81b64c; color: #fff; }
        /* Yeşil, kalın ve basılı görünümlü başlama düğmeleri */
        .btn-mode { width: 100%; padding: 16px 12px; border: none; border-radius: 14px; color: #fff; font-weight: 800; font-size: 20px; letter-spacing: 0.5px; cursor: pointer; background: #81b64c; box-shadow: 0 6px 0 #45753c, 0 10px 20px rgba(0,0,0,0.35); text-shadow: 0 2px 0 rgba(0,0,0,0.25); transition: transform 0.08s, box-shadow 0.08s, background 0.2s; }
        .btn-mode:hover { background: #95c95c; }
        .btn-mode:active { transform: translateY(5px); box-shadow: 0 1px 0 #45753c, 0 4px 10px rgba(0,0,0,0.35); }
        .btn-mode .btn-sub { display: block; font-size: 12px; font-weight: 600; opacity: 0.85; margin-top: 2px; letter-spacing: 0; }

        /* Giriş geçiş animasyonu: iki şah çarpışır */
        #transition-screen { display: none; position: fixed; inset: 0; z-index: 400; align-items: center; justify-content: center; gap: 0; background: rgba(8, 4, 24, 0.75); backdrop-filter: blur(10px); }
        #transition-screen.show { display: flex; }
        .clash-piece { font-size: 110px; line-height: 1; font-family: 'Segoe UI Symbol', 'DejaVu Sans', serif; }
        .clash-piece.l { color: #fff; text-shadow: 0 0 30px rgba(167,139,250,0.9); animation: clashL 0.7s cubic-bezier(.2,1.4,.4,1) both; }
        .clash-piece.r { color: #1e1b2e; text-shadow: 0 0 30px rgba(34,211,238,0.9); animation: clashR 0.7s cubic-bezier(.2,1.4,.4,1) both; }
        .clash-flash { position: absolute; width: 40px; height: 40px; border-radius: 50%; background: radial-gradient(circle, #fff, rgba(251,191,36,0.8) 40%, transparent 70%); animation: flash 0.6s ease-out 0.55s both; }
        @keyframes clashL { from { transform: translateX(-60vw) rotate(-30deg); } to { transform: translateX(-8px) rotate(0); } }
        @keyframes clashR { from { transform: translateX(60vw) rotate(30deg); } to { transform: translateX(8px) rotate(0); } }
        @keyframes flash { from { transform: scale(0); opacity: 1; } to { transform: scale(12); opacity: 0; } }

        /* Bot düşünüyor noktaları */
        .dots::after { content: ''; animation: dots 1.2s steps(4) infinite; }
        @keyframes dots { 0% { content: ''; } 25% { content: '.'; } 50% { content: '..'; } 75% { content: '...'; } }
        #msg.bot-think { color: #c4b5fd; }

        /* Sohbet paneli */
        #chat-panel { position: fixed; top: 0; right: 0; height: 100%; width: 320px; max-width: 86vw; background: rgba(20, 14, 48, 0.94); backdrop-filter: blur(16px); border-left: 1px solid var(--card-border); z-index: 150; display: none; flex-direction: column; transform: translateX(100%); transition: transform 0.35s cubic-bezier(.2,.8,.2,1); }
        #chat-panel.enabled { display: flex; }
        #chat-panel.open { transform: translateX(0); box-shadow: -20px 0 50px rgba(0,0,0,0.5); }
        .chat-toggle { position: absolute; left: -54px; bottom: 24px; width: 54px; height: 54px; border-radius: 16px 0 0 16px; background: linear-gradient(135deg, #8b5cf6, #06b6d4); display: flex; align-items: center; justify-content: center; font-size: 24px; cursor: pointer; box-shadow: -6px 6px 20px rgba(0,0,0,0.4); border: none; color: #fff; }
        .chat-toggle .unread { position: absolute; top: 4px; right: 6px; min-width: 18px; height: 18px; padding: 0 5px; border-radius: 9px; background: #ef4444; font-size: 11px; font-weight: 800; display: none; align-items: center; justify-content: center; animation: bump 0.6s ease infinite alternate; }
        .chat-toggle .unread.show { display: flex; }
        .chat-header { padding: 16px; font-weight: 800; font-size: 14px; text-align: center; letter-spacing: 1px; color: var(--gold); border-bottom: 1px solid var(--card-border); }
        .chat-messages { flex: 1; overflow-y: auto; padding: 14px; display: flex; flex-direction: column; gap: 8px; }
        .chat-empty { color: #94a3b8; font-size: 13px; text-align: center; margin-top: 20px; }
        .chat-msg { max-width: 82%; padding: 8px 12px; border-radius: 14px; font-size: 14px; word-wrap: break-word; animation: msgIn 0.3s ease both; }
        @keyframes msgIn { from { opacity: 0; transform: translateY(8px) scale(0.95); } to { opacity: 1; transform: none; } }
        .msg-mine { align-self: flex-end; background: linear-gradient(135deg, #8b5cf6, #6366f1); border-bottom-right-radius: 4px; }
        .msg-theirs { align-self: flex-start; background: rgba(255,255,255,0.1); border: 1px solid var(--card-border); border-bottom-left-radius: 4px; }
        .chat-input-area { display: flex; gap: 8px; padding: 12px; border-top: 1px solid var(--card-border); }
        .chat-input-area input { flex: 1; min-width: 0; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--card-border); background: rgba(10,6,30,0.6); color: #fff; outline: none; font-size: 14px; }
        .chat-input-area input:focus { border-color: var(--primary); }
        .chat-input-area button { padding: 10px 14px; border-radius: 10px; border: none; background: var(--primary); color: #fff; font-weight: 700; cursor: pointer; }

        /* Onay isteği penceresi */
        .req-text { font-size: 16px; font-weight: 700; margin: 6px 0 18px; }
        .req-icon { font-size: 40px; display: inline-block; animation: knightHop 2s ease-in-out infinite; }
        .btn-accept { background: linear-gradient(135deg, #10b981, #059669); border: none; color: #fff; border-radius: 12px; padding: 11px 20px; font-weight: 700; cursor: pointer; }
        .btn-reject { background: rgba(239,68,68,0.2); border: 1px solid rgba(239,68,68,0.5); color: #fca5a5; border-radius: 12px; padding: 11px 20px; font-weight: 700; cursor: pointer; }

        @media (prefers-reduced-motion: reduce) {
            *, *::before, *::after { animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; transition-duration: 0.01ms !important; }
            .float-piece { display: none; }
        }
    </style>
</head>
<body>
    <div id="bg-layer">
        <div class="orb o1"></div><div class="orb o2"></div><div class="orb o3"></div>
    </div>

    <div id="toast">Bağlantı Panoya Kopyalandı! 🚀</div>

    <div id="transition-screen">
        <span class="clash-piece l">♚</span>
        <div class="clash-flash"></div>
        <span class="clash-piece r">♚</span>
    </div>

    <div id="welcome-screen">
        <div class="hero" id="welcome-box">
            <div class="hero-banner">
                <div class="hero-left">
                    <h1 class="hero-title"><span>GOALTECH</span><span>CHESS</span></h1>
                    <div class="hero-art" aria-hidden="true">
                        <div class="hero-floor"></div>
                        <span class="art art-knight">&#x265E;&#xFE0E;</span>
                        <span class="art art-rook">&#x265C;&#xFE0E;</span>
                        <span class="art art-pawn">&#x265F;&#xFE0E;</span>
                    </div>
                </div>
                <div class="hero-right">
                    <div class="hero-board-frame"><div class="hero-board" id="hero-board"></div></div>
                </div>
            </div>
            <div class="hero-panel">
                <div class="input-group">
                    <label for="username">Oyuncu Adı</label>
                    <input type="text" id="username" value="Oyuncu_1" maxlength="20">
                </div>
                <div class="mode-selection" id="mode-selection">
                    <div class="mode-card bot">
                        <div>
                            <div class="mode-icon">🤖</div>
                            <h3>Bilgisayara Karşı</h3>
                            <p>Yapay zekaya meydan oku</p>
                        </div>
                        <div class="level-picker" id="level-picker">
                            <button class="level-btn" data-level="kolay" onclick="pickLevel('kolay')">Kolay</button>
                            <button class="level-btn active" data-level="orta" onclick="pickLevel('orta')">Orta</button>
                            <button class="level-btn" data-level="zor" onclick="pickLevel('zor')">Zor</button>
                        </div>
                        <button class="btn-mode bot" onclick="startGame(true)">BOTLA OYNA</button>
                    </div>
                    <div class="mode-card friend" id="friend-card">
                        <div>
                            <div class="mode-icon">👥</div>
                            <h3 id="friend-title">Arkadaşınla Oyna</h3>
                            <p id="friend-sub">Davet linki gönder, canlı oyna</p>
                        </div>
                        <button class="btn-mode friend" id="friend-btn" onclick="startGame(false)">ODA KUR</button>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div id="game-screen">
        <div class="top-bar">
            <div class="logo-title">GOALTECH <span>CHESS</span></div>
            <div class="role-badge" id="role-badge">Taraf: Beyaz</div>
        </div>

        <div class="time-picker-bar" id="time-bar">
            <span class="time-label">⏱ Süre:</span>
            <div class="time-options">
                <button class="time-btn" data-min="1" onclick="setTimeLimit(1)">1 Dk</button>
                <button class="time-btn active" data-min="3" onclick="setTimeLimit(3)">3 Dk</button>
                <button class="time-btn" data-min="5" onclick="setTimeLimit(5)">5 Dk</button>
                <button class="time-btn" data-min="10" onclick="setTimeLimit(10)">10 Dk</button>
            </div>
        </div>

        <div class="status-container">
            <div class="score-card" id="card-white">
                <div class="card-header">
                    <span class="title"><span id="w-name">Beyaz</span> (<span class="score-num" id="w-score">0</span>)</span>
                    <span class="clock-display" id="w-clock">03:00</span>
                </div>
                <div class="caps" id="w-caps"></div>
            </div>
            <div class="score-card" id="card-black">
                <div class="card-header">
                    <span class="title"><span id="b-name">Siyah</span> (<span class="score-num" id="b-score">0</span>)</span>
                    <span class="clock-display" id="b-clock">03:00</span>
                </div>
                <div class="caps" id="b-caps"></div>
            </div>
        </div>

        <div class="board-wrapper" id="board-container">
            <div class="waiting-overlay">
                <div class="wait-text">
                    <span id="wait-title">Bağlantı Bekleniyor... ⏳</span>
                    <span class="wait-sub" id="wait-sub">Arkadaşının odaya girmesi bekleniyor — "Paylaş" ile linki gönder</span>
                </div>
            </div>
            <div class="board" id="board"></div>
        </div>

        <div id="msg"></div>

        <div class="action-grid" id="action-grid">
            <button class="btn-modern btn-share" id="btn-share" onclick="nativeShare()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>
                Paylaş
            </button>
            <button class="btn-modern btn-undo" onclick="requestUndo()">↩ Geri Al</button>
            <button class="btn-modern btn-new" onclick="requestNewGame()">🔄 Yeni Oyun</button>
            <button class="btn-modern btn-logout" onclick="leaveGame()">🚪 Ana Menü</button>
        </div>
    </div>

    <div id="chat-panel">
        <button class="chat-toggle" onclick="toggleChat()" aria-label="Sohbet">💬<span class="unread" id="chat-unread">0</span></button>
        <div class="chat-header">💬 CANLI SOHBET</div>
        <div class="chat-messages" id="chat-messages"><div class="chat-empty">Henüz mesaj yok. İlk selamı sen ver! 👋</div></div>
        <div class="chat-input-area">
            <input type="text" id="chat-input" placeholder="Mesaj yaz..." maxlength="200" onkeydown="if(event.key==='Enter') sendChat()">
            <button onclick="sendChat()">Gönder</button>
        </div>
    </div>

    <div id="promo-modal" class="modal">
        <div class="modal-content">
            <h3 style="margin:0; font-size:16px;">Terfi Edecek Taşı Seç</h3>
            <div class="promo-pieces" id="promo-options"></div>
        </div>
    </div>

    <div id="request-modal" class="modal">
        <div class="modal-content">
            <div class="req-icon" id="req-icon">⏳</div>
            <div class="req-text" id="request-text">Onay bekleniyor...</div>
            <div class="modal-actions" id="req-btns">
                <button class="btn-accept" onclick="respondRequest(true)">Kabul Et</button>
                <button class="btn-reject" onclick="respondRequest(false)">Reddet</button>
            </div>
            <div class="modal-actions" id="req-cancel">
                <button class="btn-ghost" onclick="respondRequest(false)">İsteği İptal Et</button>
            </div>
        </div>
    </div>

    <div id="gameover-modal" class="modal">
        <div class="modal-content">
            <div class="gameover-icon" id="gameover-icon">🏆</div>
            <div class="gameover-title" id="gameover-title"></div>
            <div class="modal-actions">
                <button class="btn-main" onclick="requestNewGame()">🔄 Yeni Oyun</button>
                <button class="btn-ghost" onclick="closeGameOver()">Tahtaya Bak</button>
            </div>
        </div>
    </div>

    <script>
        const IMAGES = {
            'K': 'https://upload.wikimedia.org/wikipedia/commons/4/42/Chess_klt45.svg',
            'Q': 'https://upload.wikimedia.org/wikipedia/commons/1/15/Chess_qlt45.svg',
            'R': 'https://upload.wikimedia.org/wikipedia/commons/7/72/Chess_rlt45.svg',
            'B': 'https://upload.wikimedia.org/wikipedia/commons/b/b1/Chess_blt45.svg',
            'N': 'https://upload.wikimedia.org/wikipedia/commons/7/70/Chess_nlt45.svg',
            'P': 'https://upload.wikimedia.org/wikipedia/commons/4/45/Chess_plt45.svg',
            'k': 'https://upload.wikimedia.org/wikipedia/commons/f/f0/Chess_kdt45.svg',
            'q': 'https://upload.wikimedia.org/wikipedia/commons/4/47/Chess_qdt45.svg',
            'r': 'https://upload.wikimedia.org/wikipedia/commons/f/ff/Chess_rdt45.svg',
            'b': 'https://upload.wikimedia.org/wikipedia/commons/9/98/Chess_bdt45.svg',
            'n': 'https://upload.wikimedia.org/wikipedia/commons/e/ef/Chess_ndt45.svg',
            'p': 'https://upload.wikimedia.org/wikipedia/commons/c/c7/Chess_pdt45.svg'
        };
        const LEVEL_NAMES = { kolay: 'Kolay', orta: 'Orta', zor: 'Zor' };

        function storeGet(store, key) { try { return store.getItem(key); } catch (e) { return null; } }
        function storeSet(store, key, val) { try { store.setItem(key, val); } catch (e) {} }
        function storeDel(store, key) { try { store.removeItem(key); } catch (e) {} }

        // Oda linkte (?oda=...) tutulur; taraf ve bot seviyesi sekmeye özel saklanır (yenilemede korunur)
        const urlParams = new URLSearchParams(window.location.search);
        let currentRoom = urlParams.get('oda');
        let isBotMode = !!(currentRoom && currentRoom.startsWith('bot_'));
        let mySide = null;
        let botLevel = 'orta';
        if (currentRoom) {
            mySide = isBotMode ? 'beyaz' : (storeGet(sessionStorage, 'goaltech_side_' + currentRoom) || 'siyah');
            botLevel = storeGet(sessionStorage, 'goaltech_level_' + currentRoom) || 'orta';
        }

        // Her sekmenin kendine ait gizli oyuncu kimliği: linki başkası açsa da senin yerine oynayamaz
        let myId = storeGet(sessionStorage, 'goaltech_pid');
        if (!myId) {
            myId = Math.random().toString(36).substring(2) + Date.now().toString(36);
            storeSet(sessionStorage, 'goaltech_pid', myId);
        }
        const roomQ = () => 'oda=' + encodeURIComponent(currentRoom) + '&id=' + encodeURIComponent(myId);

        let playerName = storeGet(localStorage, 'goaltech_player');
        let boardState = [], selected = null, validMoves = [], whiteTurn = true, isCheck = false;
        let isProcessing = false;
        let pendingMove = null;
        let pollingTimer = null;
        let domSquares = [];
        let isBothConnected = false;
        let gameOver = false;
        let botThinking = false;
        let lastMove = null;
        let moveNo = null;
        let lastScores = null;
        let capCount = null;
        let reqSeq = 0, appliedSeq = 0;
        let fetchInFlight = false;
        let joining = false;
        let gameOverShownFor = null;
        let activeRequest = null;
        let chatSeenNo = 0, chatLastNo = 0;
        let opponentAway = false;

        spawnBackgroundPieces();
        buildHeroBoard();
        if (urlParams.get('dolu')) {
            currentRoom = null;
            try { history.replaceState(null, '', window.location.pathname); } catch (e) {}
            setTimeout(() => showToast('Bu oda dolu 😕 Yeni bir oyun başlatabilirsin.'), 300);
        }
        if (playerName) document.getElementById('username').value = playerName;

        if (currentRoom && !isBotMode && !storeGet(sessionStorage, 'goaltech_side_' + currentRoom)) {
            // Davet linkiyle gelindi: sadece "katıl" kartını göster
            document.querySelector('.mode-card.bot').style.display = 'none';
            document.getElementById('friend-title').innerText = 'Davete Katıl';
            document.getElementById('friend-sub').innerText = 'Arkadaşın seni bekliyor! ♟';
            document.getElementById('friend-btn').innerText = 'OYUNA KATIL';
        } else if (currentRoom && playerName) {
            // Sayfa yenilendi: menüyü atla
            enterRoom();
        }

        // Giriş ekranındaki tanıtım tahtası (oyundaki tahta renkleriyle)
        function buildHeroBoard() {
            const el = document.getElementById('hero-board');
            const rows = ['rnbqkbnr', 'pppppppp', '', '', '', '', 'PPPPPPPP', 'RNBQKBNR'];
            const g = { k: '\u265A', q: '\u265B', r: '\u265C', b: '\u265D', n: '\u265E', p: '\u265F' };
            for (let r = 0; r < 8; r++) {
                for (let c = 0; c < 8; c++) {
                    const sq = document.createElement('div');
                    sq.className = 'hb-sq ' + ((r + c) % 2 === 0 ? 'light' : 'dark');
                    const p = rows[r][c];
                    if (p) {
                        const s = document.createElement('span');
                        s.className = p === p.toUpperCase() ? 'w' : 'b';
                        s.textContent = g[p.toLowerCase()] + '\uFE0E';
                        s.style.animationDelay = (0.3 + (r < 2 ? r : 7 - r) * 0.12 + c * 0.04) + 's';
                        sq.appendChild(s);
                    }
                    if (c === 0) { const k = document.createElement('span'); k.className = 'hb-coord rank'; k.textContent = 8 - r; sq.appendChild(k); }
                    if (r === 7) { const k = document.createElement('span'); k.className = 'hb-coord file'; k.textContent = 'abcdefgh'[c]; sq.appendChild(k); }
                    el.appendChild(sq);
                }
            }
        }

        function spawnBackgroundPieces() {
            const layer = document.getElementById('bg-layer');
            const syms = ['♔','♕','♖','♗','♘','♙','♚','♛','♜','♝','♞','♟'];
            for (let i = 0; i < 16; i++) {
                const s = document.createElement('span');
                s.className = 'float-piece';
                s.textContent = syms[i % syms.length];
                s.style.left = (Math.random() * 100) + 'vw';
                s.style.fontSize = (28 + Math.random() * 46) + 'px';
                s.style.animationDuration = (18 + Math.random() * 22) + 's';
                s.style.animationDelay = (-Math.random() * 40) + 's';
                layer.appendChild(s);
            }
        }

        function pickLevel(level) {
            botLevel = level;
            document.querySelectorAll('.level-btn').forEach(b => b.classList.toggle('active', b.dataset.level === level));
        }

        function startGame(botMode) {
            playerName = document.getElementById('username').value.trim().slice(0, 20) || 'Oyuncu';
            storeSet(localStorage, 'goaltech_player', playerName);
            if (botMode) {
                isBotMode = true;
                currentRoom = 'bot_' + Math.random().toString(36).substring(2, 8);
                mySide = 'beyaz';
            } else if (!currentRoom || isBotMode) {
                isBotMode = false;
                currentRoom = 'oda_' + Math.random().toString(36).substring(2, 8);
                mySide = 'beyaz';
            }
            storeSet(sessionStorage, 'goaltech_side_' + currentRoom, mySide);
            storeSet(sessionStorage, 'goaltech_level_' + currentRoom, botLevel);

            document.getElementById('welcome-screen').style.display = 'none';
            const trans = document.getElementById('transition-screen');
            trans.classList.remove('show'); void trans.offsetWidth; trans.classList.add('show');
            setTimeout(() => { trans.classList.remove('show'); enterRoom(); }, 1100);
        }

        async function enterRoom() {
            try { history.replaceState(null, '', window.location.pathname + '?oda=' + encodeURIComponent(currentRoom)); } catch (e) {}
            await joinRoomLogic();
            showGame();
        }

        async function joinRoomLogic() {
            if (joining) return;
            joining = true;
            try {
                const res = await fetch('/api/join?' + roomQ() + '&taraf=' + mySide + '&ad=' + encodeURIComponent(playerName || '') + (isBotMode ? '&zorluk=' + botLevel : ''), { method: 'POST' });
                const data = await res.json();
                if (data.dolu) {
                    // Bu tarafta başka biri oynuyor: menüye dön
                    clearInterval(pollingTimer); pollingTimer = null;
                    storeDel(sessionStorage, 'goaltech_side_' + currentRoom);
                    window.location.href = window.location.pathname + '?dolu=1';
                }
            } catch (e) {
            } finally {
                joining = false;
            }
        }

        function showGame() {
            document.getElementById('welcome-screen').style.display = 'none';
            document.getElementById('game-screen').style.display = 'flex';
            const sideTxt = mySide === 'beyaz' ? 'Beyaz ♔' : 'Siyah ♚';
            document.getElementById('role-badge').innerText = playerName + ' (' + sideTxt + ')';
            document.getElementById('btn-share').style.display = isBotMode ? 'none' : '';
            document.getElementById('action-grid').classList.toggle('three', isBotMode);
            document.getElementById('chat-panel').classList.toggle('enabled', !isBotMode);

            initBoard();
            fetchState();
            if (!pollingTimer) pollingTimer = setInterval(fetchState, 400);
        }

        function showToast(text) {
            const toast = document.getElementById('toast');
            toast.innerText = text;
            toast.classList.add('show');
            setTimeout(() => toast.classList.remove('show'), 2500);
        }

        async function postJSON(url, body) {
            const res = await fetch(url, {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body || {})
            });
            return res.json();
        }

        async function nativeShare() {
            const fullLink = window.location.origin + window.location.pathname + '?oda=' + encodeURIComponent(currentRoom);
            if (navigator.share) {
                try {
                    await navigator.share({
                        title: 'Goaltech Satranç Arenası',
                        text: 'Sana meydan okuyorum! Hemen linke tıkla ve maça bağlan:',
                        url: fullLink
                    });
                } catch (err) {}
            } else if (navigator.clipboard) {
                navigator.clipboard.writeText(fullLink)
                    .then(() => showToast('Bağlantı Panoya Kopyalandı! 🚀'))
                    .catch(() => prompt('Linki kopyala:', fullLink));
            } else {
                prompt('Linki kopyala:', fullLink);
            }
        }

        function formatTime(seconds) {
            seconds = Math.max(0, seconds);
            const m = Math.floor(seconds / 60);
            const s = Math.floor(seconds % 60);
            return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
        }

        async function setTimeLimit(mins) {
            if (moveNo > 0 && !gameOver) { showToast('Oyun başladıktan sonra süre değiştirilemez'); return; }
            try {
                const data = await postJSON('/api/set_time?' + roomQ() + '&taraf=' + mySide, { minutes: mins });
                if (!data.success && data.error) showToast(data.error);
            } catch (e) {}
            await refreshNow();
        }

        async function leaveGame() {
            clearInterval(pollingTimer);
            pollingTimer = null;
            try { await fetch('/api/leave?' + roomQ() + '&taraf=' + mySide, { method: 'POST' }); } catch (e) {}
            storeDel(sessionStorage, 'goaltech_side_' + currentRoom);
            storeDel(sessionStorage, 'goaltech_level_' + currentRoom);
            window.location.href = window.location.origin + window.location.pathname;
        }

        async function requestNewGame() {
            closeGameOver();
            try {
                const data = await postJSON('/api/reset_request?' + roomQ() + '&taraf=' + mySide + (isBotMode ? '&zorluk=' + botLevel : ''));
                if (!data.success && data.error) showToast(data.error);
                if (data.done) { selected = null; validMoves = []; gameOverShownFor = null; }
            } catch (e) {}
            await refreshNow();
        }

        async function requestUndo() {
            if (isProcessing || !isBothConnected) return;
            isProcessing = true;
            try {
                const data = await postJSON('/api/undo_request?' + roomQ() + '&taraf=' + mySide);
                if (!data.success && data.error) showToast(data.error);
                selected = null; validMoves = [];
            } catch (e) {
            } finally {
                isProcessing = false;
            }
            await refreshNow();
        }

        async function respondRequest(answer) {
            if (!activeRequest) return;
            const endpoint = activeRequest === 'undo' ? '/api/undo_answer' : '/api/reset_answer';
            try { await postJSON(endpoint + '?' + roomQ(), { cevap: answer, taraf: mySide }); } catch (e) {}
            document.getElementById('request-modal').classList.remove('open');
            await refreshNow();
        }

        function closeGameOver() {
            document.getElementById('gameover-modal').classList.remove('open');
        }

        function initBoard() {
            const bEl = document.getElementById('board');
            bEl.innerHTML = '';
            domSquares = [];
            const isFlipped = (mySide === 'siyah');

            for (let i = 0; i < 8; i++) {
                let row = [];
                for (let j = 0; j < 8; j++) {
                    const r = isFlipped ? (7 - i) : i;
                    const c = isFlipped ? (7 - j) : j;
                    const sq = document.createElement('div');
                    sq.addEventListener('pointerdown', (e) => { e.preventDefault(); onSquareClick(r, c); });
                    bEl.appendChild(sq);
                    row.push({ elem: sq, r: r, c: c, piece: null, overlay: null });
                }
                domSquares.push(row);
            }
        }

        function squareEl(r, c) {
            for (const row of domSquares) for (const s of row) if (s.r === r && s.c === c) return s.elem;
            return null;
        }

        async function refreshNow() {
            fetchInFlight = false;   // bekleyen yoklamayı beklemeden en güncel durumu çek
            await fetchState();
        }

        async function fetchState() {
            if (fetchInFlight || !currentRoom) return;
            fetchInFlight = true;
            const mySeq = ++reqSeq;
            try {
                const res = await fetch('/api/state?' + roomQ() + '&taraf=' + mySide);
                const data = await res.json();
                if (mySeq < appliedSeq) return;   // eski cevap, yoksay
                appliedSeq = mySeq;
                applyState(data);
            } catch (e) {
            } finally {
                if (mySeq === reqSeq) fetchInFlight = false;
            }
        }

        function applyState(data) {
            // Sunucu yeniden başlarsa oda kaybolur; bu durumda odaya tekrar katıl
            const meJoined = mySide === 'beyaz' ? data.beyaz_katildi : data.siyah_katildi;
            if (!meJoined && playerName) joinRoomLogic();

            const prevMoveNo = moveNo;
            boardState = data.tahta;
            whiteTurn = data.beyaz_sirasi;
            isCheck = data.sah_tehdit;
            gameOver = data.oyun_bitti;
            lastMove = data.son_hamle;
            moveNo = data.hamle_no;
            botThinking = data.bot_dusunuyor;
            isBothConnected = data.siyah_katildi && data.beyaz_katildi;

            if (prevMoveNo !== null && prevMoveNo !== moveNo) { selected = null; validMoves = []; }

            // Bekleme / rakip çıktı katmanı
            const oppSide = mySide === 'beyaz' ? 'siyah' : 'beyaz';
            opponentAway = !!data[oppSide + '_katildi'] && !data[oppSide + '_baglandi'];
            document.getElementById('board-container').classList.toggle('waiting', !isBothConnected);
            document.getElementById('time-bar').classList.toggle('locked', moveNo > 0 && !gameOver);

            // İsimler
            document.getElementById('w-name').innerText = data.beyaz_ad || 'Beyaz';
            document.getElementById('b-name').innerText = data.bot ? '🤖 Bot · ' + (LEVEL_NAMES[data.zorluk] || '') : (data.siyah_ad || 'Siyah');

            const wScoreEl = document.getElementById('w-score');
            const bScoreEl = document.getElementById('b-score');
            if (lastScores) {
                if (data.b_skor > lastScores[0]) bumpEl(wScoreEl);
                if (data.s_skor > lastScores[1]) bumpEl(bScoreEl);
            }
            lastScores = [data.b_skor, data.s_skor];
            wScoreEl.innerText = data.b_skor;
            bScoreEl.innerText = data.s_skor;
            document.getElementById('w-caps').innerText = data.y_siyah.join(' ');
            document.getElementById('b-caps').innerText = data.y_beyaz.join(' ');

            const wClock = document.getElementById('w-clock');
            const bClock = document.getElementById('b-clock');
            wClock.innerText = formatTime(data.beyaz_sure);
            bClock.innerText = formatTime(data.siyah_sure);
            wClock.classList.toggle('danger', !gameOver && data.beyaz_sure <= 30 && whiteTurn);
            bClock.classList.toggle('danger', !gameOver && data.siyah_sure <= 30 && !whiteTurn);

            document.querySelectorAll('.time-btn').forEach(btn => {
                btn.classList.toggle('active', Number(btn.dataset.min) === Number(data.secili_dakika));
            });

            updateMessage(data.mesaj);

            document.getElementById('card-white').classList.toggle('active-turn', !gameOver && whiteTurn);
            document.getElementById('card-black').classList.toggle('active-turn', !gameOver && !whiteTurn);

            const newCaps = data.y_beyaz.length + data.y_siyah.length;
            const wasCapture = capCount !== null && newCaps > capCount;
            capCount = newCaps;

            render();

            if (prevMoveNo !== null && moveNo === prevMoveNo + 1 && lastMove) {
                animateLastMove(wasCapture);
            }

            if (gameOver && gameOverShownFor !== moveNo) {
                gameOverShownFor = moveNo;
                showGameOver(data);
            }
            if (!gameOver) { gameOverShownFor = null; closeGameOver(); }

            updateRequestModal(data);
            if (!isBotMode) updateChat(data.chat || []);
        }

        function updateMessage(serverMsg) {
            const msg = document.getElementById('msg');
            if (serverMsg) { msg.innerText = serverMsg; msg.className = ''; return; }
            if (!isBothConnected) { msg.innerText = ''; msg.className = ''; return; }
            if (botThinking) { msg.innerText = 'Bot düşünüyor 🤖'; msg.className = 'bot-think dots'; return; }
            if (opponentAway) { msg.innerText = 'Rakibin bağlantısı koptu, geri dönmesi bekleniyor ⚠️'; msg.className = ''; return; }
            const myTurn = (mySide === 'beyaz') === whiteTurn;
            if (isCheck && myTurn) { msg.innerText = 'ŞAH! Şahını korumalısın ⚠️'; msg.className = ''; return; }
            msg.innerText = myTurn ? 'Sıra sende ✨' : 'Rakip düşünüyor... 🤔';
            msg.className = myTurn ? 'my-turn' : 'info';
        }

        function updateRequestModal(data) {
            const modal = document.getElementById('request-modal');
            const req = data.undo_istegi ? 'undo' : (data.reset_istegi ? 'reset' : null);
            activeRequest = req;
            if (!req) { modal.classList.remove('open'); return; }
            const requester = data.undo_istegi || data.reset_istegi;
            const mine = requester === mySide;
            let text;
            if (req === 'undo') text = mine ? 'Rakibinin geri alma onayı bekleniyor...' : 'Rakibin son hamlesini geri almak istiyor. Kabul ediyor musun?';
            else text = mine ? 'Rakibinin yeni oyun onayı bekleniyor...' : 'Rakibin yeni bir oyun başlatmak istiyor. Tahta sıfırlansın mı?';
            document.getElementById('request-text').innerText = text;
            document.getElementById('req-icon').innerText = mine ? '⏳' : (req === 'undo' ? '↩️' : '🔄');
            document.getElementById('req-btns').style.display = mine ? 'none' : 'flex';
            document.getElementById('req-cancel').style.display = mine ? 'flex' : 'none';
            if (!modal.classList.contains('open')) modal.classList.add('open');
        }

        function updateChat(chat) {
            const panel = document.getElementById('chat-panel');
            const isOpen = panel.classList.contains('open');
            const newestNo = chat.length ? chat[chat.length - 1].no : 0;
            const box = document.getElementById('chat-messages');
            if (newestNo < chatLastNo) { box.innerHTML = ''; chatLastNo = 0; chatSeenNo = 0; }  // sunucu sıfırlandı
            const fresh = chat.filter(m => m.no > chatLastNo);
            if (fresh.length) {
                if (chatLastNo === 0) box.innerHTML = '';
                fresh.forEach(m => {
                    const div = document.createElement('div');
                    div.className = 'chat-msg ' + (m.taraf === mySide ? 'msg-mine' : 'msg-theirs');
                    div.innerText = m.metin;
                    box.appendChild(div);
                });
                while (box.children.length > 100) box.removeChild(box.firstChild);
                box.scrollTop = box.scrollHeight;
                chatLastNo = newestNo;
            }
            if (isOpen) chatSeenNo = chatLastNo;
            const unread = chat.filter(m => m.no > chatSeenNo && m.taraf !== mySide).length;
            const badge = document.getElementById('chat-unread');
            badge.innerText = unread;
            badge.classList.toggle('show', unread > 0);
        }

        function toggleChat() {
            const panel = document.getElementById('chat-panel');
            panel.classList.toggle('open');
            if (panel.classList.contains('open')) {
                chatSeenNo = chatLastNo;
                document.getElementById('chat-unread').classList.remove('show');
                setTimeout(() => document.getElementById('chat-input').focus(), 300);
            }
        }

        async function sendChat() {
            const input = document.getElementById('chat-input');
            const text = input.value.trim();
            if (!text) return;
            input.value = '';
            try { await postJSON('/api/chat_send?' + roomQ(), { taraf: mySide, metin: text }); } catch (e) {}
            await refreshNow();
        }

        function bumpEl(el) {
            el.classList.remove('bump');
            void el.offsetWidth;
            el.classList.add('bump');
        }

        // Görsel yüklenemezse (internet/engelleme) Unicode taş sembolüne düş
        const GLYPHS = { k: '♚', q: '♛', r: '♜', b: '♝', n: '♞', p: '♟' };
        function makePieceEl(piece) {
            const img = document.createElement('img');
            img.className = 'piece';
            img.src = IMAGES[piece];
            img.alt = piece;
            img.draggable = false;
            img.onerror = () => {
                const g = document.createElement('span');
                g.className = 'piece glyph ' + (piece === piece.toUpperCase() ? 'glyph-w' : 'glyph-b');
                g.textContent = GLYPHS[piece.toLowerCase()];
                img.replaceWith(g);
            };
            return img;
        }

        function render() {
            if (!boardState || boardState.length === 0 || domSquares.length === 0) return;
            const lmSquares = lastMove ? lastMove.flatMap(m => [m[0], m[1]]) : [];

            for (let i = 0; i < 8; i++) {
                for (let j = 0; j < 8; j++) {
                    const cacheData = domSquares[i][j];
                    const r = cacheData.r;
                    const c = cacheData.c;
                    const sq = cacheData.elem;
                    const piece = boardState[r][c];
                    const isValid = validMoves.some(m => m[0] === r && m[1] === c);

                    let classStr = 'square ' + ((r + c) % 2 === 0 ? 'light' : 'dark');
                    if (lmSquares.some(s => s[0] === r && s[1] === c)) classStr += ' last-move';
                    if (selected && selected[0] === r && selected[1] === c) classStr += ' selected';
                    if (isCheck && ((whiteTurn && piece === 'K') || (!whiteTurn && piece === 'k'))) classStr += ' in-check';
                    if (sq.className !== classStr) sq.className = classStr;

                    // Taş görselini sadece değiştiğinde güncelle (titreme olmasın)
                    if (cacheData.piece !== piece) {
                        const oldImg = sq.querySelector('.piece');
                        if (oldImg) oldImg.remove();
                        if (piece !== ' ') sq.prepend(makePieceEl(piece));
                        cacheData.piece = piece;
                    }

                    const overlay = isValid ? (piece !== ' ' ? 'ring' : 'dot') : null;
                    if (cacheData.overlay !== overlay) {
                        const old = sq.querySelector('.valid-dot, .valid-ring');
                        if (old) old.remove();
                        if (overlay) {
                            const d = document.createElement('div');
                            d.className = overlay === 'dot' ? 'valid-dot' : 'valid-ring';
                            sq.appendChild(d);
                        }
                        cacheData.overlay = overlay;
                    }
                }
            }
        }

        function animateLastMove(wasCapture) {
            lastMove.forEach(([from, to], idx) => {
                const fromEl = squareEl(from[0], from[1]);
                const toEl = squareEl(to[0], to[1]);
                if (!fromEl || !toEl) return;
                const img = toEl.querySelector('.piece');
                if (!img || !img.animate) return;
                const a = fromEl.getBoundingClientRect();
                const b = toEl.getBoundingClientRect();
                const dx = a.left - b.left, dy = a.top - b.top;
                img.style.zIndex = 40;
                const anim = img.animate([
                    { transform: `translate(${dx}px, ${dy}px) scale(1.15)` },
                    { transform: 'translate(0, 0) scale(1)' }
                ], { duration: 320, easing: 'cubic-bezier(.2,.8,.2,1)' });
                anim.onfinish = () => { img.style.zIndex = ''; };
                if (idx === 0 && wasCapture) {
                    setTimeout(() => {
                        const burst = document.createElement('div');
                        burst.className = 'capture-burst';
                        toEl.appendChild(burst);
                        setTimeout(() => burst.remove(), 600);
                    }, 260);
                }
            });
        }

        function showGameOver(data) {
            const title = document.getElementById('gameover-title');
            const icon = document.getElementById('gameover-icon');
            title.innerText = data.mesaj || 'Oyun Bitti';
            const t = data.sonuc_tipi;
            if (t === 'mat' || t === 'sure') {
                const whiteWon = !data.beyaz_sirasi;
                const iWon = (mySide === 'beyaz') === whiteWon;
                icon.innerText = iWon ? '🏆' : (isBotMode ? '🤖' : '😔');
                if (iWon) launchConfetti();
            } else {
                icon.innerText = '🤝';
            }
            document.getElementById('gameover-modal').classList.add('open');
        }

        function launchConfetti() {
            const colors = ['#8b5cf6', '#22d3ee', '#fbbf24', '#f472b6', '#34d399'];
            for (let i = 0; i < 90; i++) {
                const c = document.createElement('div');
                c.className = 'confetti';
                c.style.left = Math.random() * 100 + 'vw';
                c.style.background = colors[i % colors.length];
                c.style.animationDuration = (2 + Math.random() * 2.5) + 's';
                c.style.animationDelay = (Math.random() * 0.8) + 's';
                c.style.borderRadius = Math.random() > 0.5 ? '50%' : '2px';
                document.body.appendChild(c);
                setTimeout(() => c.remove(), 5500);
            }
        }

        function shakeBoard() {
            const b = document.getElementById('board');
            b.classList.remove('shake');
            void b.offsetWidth;
            b.classList.add('shake');
        }

        async function onSquareClick(r, c) {
            if (!isBothConnected || gameOver || activeRequest) return;

            const isMyTurn = (mySide === 'beyaz' && whiteTurn) || (mySide === 'siyah' && !whiteTurn);
            if (!isMyTurn || isProcessing) return;

            const piece = boardState[r][c];

            if (selected && validMoves.some(m => m[0] === r && m[1] === c)) {
                const selPiece = boardState[selected[0]][selected[1]];
                if (selPiece.toUpperCase() === 'P' && (r === 0 || r === 7)) {
                    showPromoModal(selected, [r, c]);
                    return;
                }
                await sendMove(selected, [r, c]);
                return;
            }

            const isWhitePiece = piece !== ' ' && piece === piece.toUpperCase();
            const isBlackPiece = piece !== ' ' && piece === piece.toLowerCase();

            if (selected && selected[0] === r && selected[1] === c) {
                selected = null; validMoves = []; render();
                return;
            }

            if ((whiteTurn && isWhitePiece && mySide === 'beyaz') || (!whiteTurn && isBlackPiece && mySide === 'siyah')) {
                selected = [r, c];
                validMoves = [];
                render();
                isProcessing = true;
                try {
                    const data = await postJSON('/api/valid_moves?' + roomQ(), { r, c, taraf: mySide });
                    if (selected && selected[0] === r && selected[1] === c) {
                        validMoves = data.moves || [];
                        if (validMoves.length === 0) shakeBoard();
                    }
                } catch (e) {
                } finally {
                    isProcessing = false;
                    render();
                }
            } else {
                if (selected && piece === ' ') shakeBoard();
                selected = null; validMoves = []; render();
            }
        }

        function showPromoModal(from, to) {
            pendingMove = { from, to };
            const opts = document.getElementById('promo-options');
            opts.innerHTML = '';
            const pieces = mySide === 'beyaz' ? ['Q', 'R', 'B', 'N'] : ['q', 'r', 'b', 'n'];
            pieces.forEach(p => {
                const item = document.createElement('div');
                item.className = 'promo-piece';
                item.appendChild(makePieceEl(p));
                item.onclick = (e) => { e.stopPropagation(); selectPromotion(p); };
                opts.appendChild(item);
            });
            document.getElementById('promo-modal').classList.add('open');
        }

        // Telefonda başka uygulamadan dönülünce durumu hemen güncelle
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden && pollingTimer) refreshNow();
        });

        // Terfi penceresinin dışına tıklayınca iptal et
        document.getElementById('promo-modal').addEventListener('click', (e) => {
            if (e.target.id === 'promo-modal') {
                e.currentTarget.classList.remove('open');
                pendingMove = null;
            }
        });

        async function selectPromotion(pieceChoice) {
            document.getElementById('promo-modal').classList.remove('open');
            if (!pendingMove) return;
            const mv = pendingMove;
            pendingMove = null;
            await sendMove(mv.from, mv.to, pieceChoice);
        }

        async function sendMove(from, to, promo = null) {
            isProcessing = true;
            try {
                const data = await postJSON('/api/move?' + roomQ(), { from: from, to: to, promotion: promo, taraf: mySide });
                selected = null; validMoves = [];
                if (!data.success) {
                    document.getElementById('msg').innerText = data.error || 'Hamle yapılamadı';
                    document.getElementById('msg').className = '';
                    shakeBoard();
                }
            } catch (e) {
                document.getElementById('msg').innerText = 'Bağlantı hatası, tekrar dene.';
            } finally {
                isProcessing = false;
            }
            await refreshNow();
        }
    </script>
</body>
</html>"""


# =====================================================================
# 6. ODA YARDIMCILARI VE API ROTLARI
# =====================================================================
BAGLANTI_ZAMAN_ASIMI = 30  # saniye boyunca haber gelmezse oyuncu "çıktı" sayılır
BOT_BEKLEME = 0.6          # bot hamle yapmadan önce kısa bir "düşünme" süresi
GECMIS_ANAHTARLARI = ('tahta', 'beyaz_sirasi', 'b_skor', 's_skor', 'y_beyaz', 'y_siyah') + ROK_ANAHTARLARI + (
    'gecerken', 'elli_sayac', 'beyaz_sure', 'siyah_sure', 'konum_gecmisi', 'son_hamle', 'oyun_basladi')
KORUNAN_ALANLAR = ('beyaz_baglandi', 'siyah_baglandi', 'beyaz_son', 'siyah_son', 'beyaz_id', 'siyah_id',
                   'beyaz_ad', 'siyah_ad', 'bot', 'zorluk', 'chat', 'chat_sayac')

def odalari_temizle():
    simdi = time.time()
    for oda_id in [k for k, v in odalar.items() if simdi - v['son_erisim'] > ODA_ZAMAN_ASIMI]:
        del odalar[oda_id]

def oda_id_al():
    return (request.args.get('oda') or 'varsayilan')[:64]

def get_or_create_room(oda_id):
    if oda_id not in odalar:
        odalari_temizle()
        oda = yeni_oda_olustur()
        if oda_id.startswith('bot_'):
            oda['bot'] = True
            oda['siyah_baglandi'] = True
            oda['siyah_ad'] = 'Bot'
        odalar[oda_id] = oda
    oda = odalar[oda_id]
    oda['son_erisim'] = time.time()
    return oda

def odayi_sifirla(oda_id, dakika=None):
    eski = odalar[oda_id]
    yeni = yeni_oda_olustur(dakika or eski['secili_dakika'])
    for k in KORUNAN_ALANLAR:
        yeni[k] = eski[k]
    odalar[oda_id] = yeni
    return yeni

def kare_al(deger):
    try:
        r, c = int(deger[0]), int(deger[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    if 0 <= r < 8 and 0 <= c < 8:
        return r, c
    return None

def taraf_dogru_mu(oda, taraf):
    if taraf not in ('beyaz', 'siyah'):
        return False
    if oda['bot'] and taraf != 'beyaz':
        return False
    return (taraf == 'beyaz') == oda['beyaz_sirasi']

def yetkili_mi(oda, taraf):
    """İsteği gönderen sekme bu tarafın sahibi mi? (davet linkini ele geçirmeyi engeller)"""
    if taraf not in ('beyaz', 'siyah') or (oda['bot'] and taraf == 'siyah'):
        return False
    kayitli = oda[f'{taraf}_id']
    return not kayitli or kayitli == (request.args.get('id') or '')

def katildi_mi(oda, taraf):
    return oda[f'{taraf}_baglandi']

def bagli_mi(oda, taraf):
    if oda['bot'] and taraf == 'siyah':
        return True
    return oda[f'{taraf}_baglandi'] and time.time() - oda[f'{taraf}_son'] < BAGLANTI_ZAMAN_ASIMI

def gecmise_kaydet(oda):
    oda['hamle_gecmisi'].append({k: copy.deepcopy(oda[k]) for k in GECMIS_ANAHTARLARI})

def gecmisten_geri_al(oda, adet):
    for _ in range(adet):
        if not oda['hamle_gecmisi']:
            break
        eski = oda['hamle_gecmisi'].pop()
        for k in GECMIS_ANAHTARLARI:
            oda[k] = eski[k]
    oda['son_zaman'] = time.time()
    oda['oyun_bitti'] = False
    oda['sonuc_tipi'] = ''
    oda['mesaj'] = ''

def hamle_yap(oda, b_sat, b_sut, h_sat, h_sut, terfi=None):
    """Geçerliliği kontrol edilmiş bir hamleyi odaya uygular ve oyun sonunu denetler."""
    tahta = oda['tahta']
    secilen = tahta[b_sat][b_sut]
    gecmise_kaydet(oda)

    oda['oyun_basladi'] = True
    oda['son_zaman'] = time.time()
    oda['son_hamle_zamani'] = time.time()
    oda['mesaj'] = ''
    oda['undo_istegi'] = None
    oda['reset_istegi'] = None

    alinan, ek = hamle_uygula(oda, b_sat, b_sut, h_sat, h_sut, terfi)
    if alinan:
        puan = TAS_PUANLARI.get(alinan.upper(), 0)
        if oda['beyaz_sirasi']:
            oda['b_skor'] += puan; oda['y_siyah'].append(SEMBOLLER[alinan])
        else:
            oda['s_skor'] += puan; oda['y_beyaz'].append(SEMBOLLER[alinan])

    oda['elli_sayac'] = 0 if (secilen.upper() == 'P' or alinan) else oda['elli_sayac'] + 1
    oda['son_hamle'] = [[[b_sat, b_sut], [h_sat, h_sut]]] + ek
    oda['beyaz_sirasi'] = not oda['beyaz_sirasi']

    durum_anahtari = tahta_durum_anahtari(oda)
    oda['konum_gecmisi'][durum_anahtari] = oda['konum_gecmisi'].get(durum_anahtari, 0) + 1

    s_r, s_c = sah_konumu_bul(tahta, oda['beyaz_sirasi'])
    tehdit = tehdit_altinda_mi(tahta, s_r, s_c, not oda['beyaz_sirasi']) if s_r != -1 else False
    kalan_hamle = tum_gecerli_hamleler_sayisi(oda, oda['beyaz_sirasi'])

    if kalan_hamle == 0:
        if tehdit:
            kazanan = 'Beyaz' if not oda['beyaz_sirasi'] else 'Siyah'
            if oda['bot']:
                kazanan_metin = 'Kazandın! 🎉' if kazanan == 'Beyaz' else 'Bot Kazandı! 🤖'
                oyunu_bitir(oda, f"ŞAH MAT! {kazanan_metin}", kazanan, 'mat')
            else:
                oyunu_bitir(oda, f"ŞAH MAT! {kazanan} Kazandı!", kazanan, 'mat')
        else:
            oyunu_bitir(oda, "PAT! Oyun Berabere.", "BERABERE", 'berabere')
    elif oda['elli_sayac'] >= 100:
        oyunu_bitir(oda, "50 Hamle Kuralı Nedeniyle Berabere!", "BERABERE", 'berabere')
    elif oda['konum_gecmisi'].get(durum_anahtari, 0) >= 3:
        oyunu_bitir(oda, "3 Kez Konum Tekrarı Nedeniyle Berabere!", "BERABERE", 'berabere')
    elif yetersiz_materyal_mi(tahta):
        oyunu_bitir(oda, "Yetersiz Materyal Nedeniyle Berabere!", "BERABERE", 'berabere')

def bot_oynat(oda_id):
    """Sıra bottaysa hamlesini hesaplar. Ağır hesap kilit dışında yapılır."""
    with kilit:
        oda = odalar.get(oda_id)
        if (not oda or not oda['bot'] or oda['oyun_bitti'] or oda['beyaz_sirasi']
                or oda['bot_hesapliyor'] or oda['undo_istegi'] or oda['reset_istegi']):
            return
        if time.time() - oda.get('son_hamle_zamani', 0) < BOT_BEKLEME:
            return
        oda['bot_hesapliyor'] = True
        durum = durum_kopyala(oda)
        hamle_no = len(oda['hamle_gecmisi'])
        zorluk = oda['zorluk']
        kalan = oda['siyah_sure']
    try:
        hamle = bot_hamlesi_sec(durum, False, zorluk, kalan)
    finally:
        with kilit:
            oda['bot_hesapliyor'] = False
    with kilit:
        # Bu arada oda sıfırlandıysa / geri alındıysa hamleyi uygulama
        if (hamle and odalar.get(oda_id) is oda and len(oda['hamle_gecmisi']) == hamle_no
                and not oda['beyaz_sirasi'] and not oda['oyun_bitti']):
            sure_guncelle(oda)
            if not oda['oyun_bitti']:
                hamle_yap(oda, *hamle)

@app.route('/')
def home():
    return HTML_PAGE

@app.route('/api/join', methods=['POST'])
def api_join():
    with kilit:
        oda = get_or_create_room(oda_id_al())
        taraf = request.args.get('taraf', 'beyaz')
        ad = (request.args.get('ad') or '').strip()[:20]
        zorluk = request.args.get('zorluk')
        if oda['bot']:
            taraf = 'beyaz'
            if zorluk in ('kolay', 'orta', 'zor') and not oda['hamle_gecmisi']:
                oda['zorluk'] = zorluk
        if taraf not in ('beyaz', 'siyah'):
            return jsonify({'success': False, 'error': 'Geçersiz taraf'})
        kimlik = (request.args.get('id') or '')[:40]
        if oda[f'{taraf}_id'] and oda[f'{taraf}_id'] != kimlik and bagli_mi(oda, taraf):
            return jsonify({'success': False, 'dolu': True, 'error': 'Bu oda dolu, iki oyuncu zaten oynuyor.'})
        oda[f'{taraf}_id'] = kimlik
        oda[f'{taraf}_baglandi'] = True
        oda[f'{taraf}_son'] = time.time()
        if ad: oda[f'{taraf}_ad'] = ad
        return jsonify({'success': True})

@app.route('/api/leave', methods=['POST'])
def api_leave():
    with kilit:
        oda_id = oda_id_al()
        taraf = request.args.get('taraf')
        if oda_id in odalar:
            oda = odalar[oda_id]
            if oda['bot']:
                del odalar[oda_id]
            elif yetkili_mi(oda, taraf):
                oda[f'{taraf}_son'] = 0
        return jsonify({'success': True})

@app.route('/api/set_time', methods=['POST'])
def api_set_time():
    with kilit:
        oda_id = oda_id_al()
        oda = get_or_create_room(oda_id)
        data = request.get_json(silent=True) or {}
        try:
            mins = int(data.get('minutes', 3))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Geçersiz süre'})
        if mins not in IZINLI_DAKIKALAR:
            return jsonify({'success': False, 'error': 'Geçersiz süre'})
        if not yetkili_mi(oda, request.args.get('taraf')):
            return jsonify({'success': False, 'error': 'Geçersiz taraf'})
        if oda['hamle_gecmisi'] and not oda['oyun_bitti']:
            return jsonify({'success': False, 'error': 'Oyun başladıktan sonra süre değiştirilemez'})
        odayi_sifirla(oda_id, mins)
        return jsonify({'success': True})

@app.route('/api/state')
def api_state():
    oda_id = oda_id_al()
    with kilit:
        oda = get_or_create_room(oda_id)
        taraf = request.args.get('taraf')
        if taraf in ('beyaz', 'siyah') and oda[f'{taraf}_baglandi'] and yetkili_mi(oda, taraf):
            oda[f'{taraf}_son'] = time.time()
    bot_oynat(oda_id)
    with kilit:
        oda = get_or_create_room(oda_id)
        sure_guncelle(oda)
        k_sat, k_sut = sah_konumu_bul(oda['tahta'], oda['beyaz_sirasi'])
        sah_tehdidi = tehdit_altinda_mi(oda['tahta'], k_sat, k_sut, not oda['beyaz_sirasi']) if k_sat != -1 else False
        return jsonify({
            'tahta': oda['tahta'], 'beyaz_sirasi': oda['beyaz_sirasi'], 'sah_tehdit': sah_tehdidi,
            'b_skor': oda['b_skor'], 's_skor': oda['s_skor'],
            'y_beyaz': oda['y_beyaz'], 'y_siyah': oda['y_siyah'], 'mesaj': oda['mesaj'],
            'secili_dakika': oda['secili_dakika'],
            'beyaz_sure': round(oda['beyaz_sure']),
            'siyah_sure': round(oda['siyah_sure']),
            'beyaz_baglandi': bagli_mi(oda, 'beyaz'),
            'siyah_baglandi': bagli_mi(oda, 'siyah'),
            'beyaz_katildi': oda['beyaz_baglandi'],
            'siyah_katildi': oda['siyah_baglandi'],
            'beyaz_ad': oda['beyaz_ad'], 'siyah_ad': oda['siyah_ad'],
            'oyun_bitti': oda['oyun_bitti'],
            'sonuc_tipi': oda['sonuc_tipi'],
            'son_hamle': oda['son_hamle'],
            'hamle_no': len(oda['hamle_gecmisi']),
            'bot': oda['bot'], 'zorluk': oda['zorluk'],
            'bot_dusunuyor': oda['bot'] and not oda['oyun_bitti'] and not oda['beyaz_sirasi'],
            'undo_istegi': oda['undo_istegi'],
            'reset_istegi': oda['reset_istegi'],
            'chat': oda['chat']
        })

@app.route('/api/valid_moves', methods=['POST'])
def api_valid():
    with kilit:
        oda = get_or_create_room(oda_id_al())
        req = request.get_json(silent=True) or {}
        kare = kare_al([req.get('r'), req.get('c')])
        if (kare is None or oda['oyun_bitti'] or not taraf_dogru_mu(oda, req.get('taraf'))
                or not yetkili_mi(oda, req.get('taraf'))):
            return jsonify({'moves': []})
        return jsonify({'moves': gecerli_hamleleri_bul(oda, kare[0], kare[1], oda['beyaz_sirasi'])})

@app.route('/api/move', methods=['POST'])
def api_move():
    with kilit:
        oda = get_or_create_room(oda_id_al())
        data = request.get_json(silent=True) or {}
        bas = kare_al(data.get('from'))
        hed = kare_al(data.get('to'))
        if bas is None or hed is None:
            return jsonify({'success': False, 'error': 'Geçersiz hamle verisi!'})

        # Önce süreyi düş: süre bittiyse hamle kabul edilmez
        sure_guncelle(oda)
        if oda['oyun_bitti']:
            return jsonify({'success': False, 'error': 'Oyun bitti!'})
        if not (katildi_mi(oda, 'beyaz') and katildi_mi(oda, 'siyah')):
            return jsonify({'success': False, 'error': 'Rakip henüz odaya katılmadı!'})
        if not yetkili_mi(oda, data.get('taraf')):
            return jsonify({'success': False, 'error': 'Bu tarafı oynama yetkin yok!'})
        if not taraf_dogru_mu(oda, data.get('taraf')):
            return jsonify({'success': False, 'error': 'Sıra sende değil!'})
        if [hed[0], hed[1]] not in gecerli_hamleleri_bul(oda, bas[0], bas[1], oda['beyaz_sirasi']):
            return jsonify({'success': False, 'error': 'Kural dışı hamle!'})

        hamle_yap(oda, bas[0], bas[1], hed[0], hed[1], data.get('promotion'))
        return jsonify({'success': True})

def undo_adedi(oda, taraf):
    """İsteyen tarafın son hamlesini geri almak için kaç yarım hamle geri gidilmeli."""
    sira_bende = (taraf == 'beyaz') == oda['beyaz_sirasi']
    adet = 2 if sira_bende else 1
    return adet if len(oda['hamle_gecmisi']) >= adet else 0

@app.route('/api/undo_request', methods=['POST'])
def api_undo_request():
    with kilit:
        oda = get_or_create_room(oda_id_al())
        taraf = request.args.get('taraf')
        if not yetkili_mi(oda, taraf):
            return jsonify({'success': False, 'error': 'Geçersiz taraf'})
        if oda['bot']:
            if oda['bot_hesapliyor']:
                return jsonify({'success': False, 'error': 'Bot düşünürken geri alınamaz'})
        adet = undo_adedi(oda, taraf)
        if adet == 0:
            return jsonify({'success': False, 'error': 'Geri alınacak hamle yok'})
        if oda['bot']:
            gecmisten_geri_al(oda, adet)  # bota sormaya gerek yok
            return jsonify({'success': True, 'done': True})
        if oda['undo_istegi'] or oda['reset_istegi']:
            return jsonify({'success': False, 'error': 'Zaten bekleyen bir istek var'})
        oda['undo_istegi'] = taraf
        oda['undo_hamle_no'] = len(oda['hamle_gecmisi'])
        return jsonify({'success': True})

@app.route('/api/undo_answer', methods=['POST'])
def api_undo_answer():
    with kilit:
        oda = get_or_create_room(oda_id_al())
        data = request.get_json(silent=True) or {}
        taraf, cevap = data.get('taraf'), bool(data.get('cevap'))
        isteyen = oda['undo_istegi']
        if not isteyen or not yetkili_mi(oda, taraf):
            return jsonify({'success': False})
        if taraf == isteyen:
            if not cevap:
                oda['undo_istegi'] = None  # isteyen iptal etti
            return jsonify({'success': True})
        oda['undo_istegi'] = None
        if cevap and len(oda['hamle_gecmisi']) == oda['undo_hamle_no']:
            adet = undo_adedi(oda, isteyen)
            if adet:
                gecmisten_geri_al(oda, adet)
        return jsonify({'success': True})

@app.route('/api/reset_request', methods=['POST'])
def api_reset_request():
    with kilit:
        oda_id = oda_id_al()
        oda = get_or_create_room(oda_id)
        taraf = request.args.get('taraf')
        if not yetkili_mi(oda, taraf):
            return jsonify({'success': False, 'error': 'Geçersiz taraf'})
        # Bot oyununda, biten oyunda veya hiç hamle yapılmadıysa onay gerekmez
        if oda['bot'] or oda['oyun_bitti'] or not oda['hamle_gecmisi']:
            yeni = odayi_sifirla(oda_id)
            zorluk = request.args.get('zorluk')
            if yeni['bot'] and zorluk in ('kolay', 'orta', 'zor'):
                yeni['zorluk'] = zorluk
            return jsonify({'success': True, 'done': True})
        if oda['undo_istegi'] or oda['reset_istegi']:
            return jsonify({'success': False, 'error': 'Zaten bekleyen bir istek var'})
        oda['reset_istegi'] = taraf
        return jsonify({'success': True})

@app.route('/api/reset_answer', methods=['POST'])
def api_reset_answer():
    with kilit:
        oda_id = oda_id_al()
        oda = get_or_create_room(oda_id)
        data = request.get_json(silent=True) or {}
        taraf, cevap = data.get('taraf'), bool(data.get('cevap'))
        isteyen = oda['reset_istegi']
        if not isteyen or not yetkili_mi(oda, taraf):
            return jsonify({'success': False})
        if taraf == isteyen:
            if not cevap:
                oda['reset_istegi'] = None
            return jsonify({'success': True})
        oda['reset_istegi'] = None
        if cevap:
            odayi_sifirla(oda_id)
        return jsonify({'success': True})

@app.route('/api/chat_send', methods=['POST'])
def api_chat_send():
    with kilit:
        oda = get_or_create_room(oda_id_al())
        data = request.get_json(silent=True) or {}
        taraf = data.get('taraf')
        metin = str(data.get('metin') or '').strip()[:200]
        if oda['bot'] or not yetkili_mi(oda, taraf) or not metin:
            return jsonify({'success': False})
        oda['chat_sayac'] += 1
        oda['chat'].append({'no': oda['chat_sayac'], 'taraf': taraf, 'metin': metin})
        del oda['chat'][:-100]  # son 100 mesaj tutulur
        return jsonify({'success': True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
