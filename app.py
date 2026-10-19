import os
import json
import time
import sqlite3
import jwt
from flask import Flask, jsonify, request

app = Flask(__name__)

# =====================================================================
# 1. VERİLER VE OYUN DURUMU
# =====================================================================
KAYITLI_KULLANICI = "vahit"
KAYITLI_SIFRE = "yasin12345"
SECRET_KEY = "goaltech_secret_key"

SEMBOLLER = {'K':'♔','Q':'♕','R':'♖','B':'♗','N':'♘','P':'♙', 'k':'♚','q':'♛','r':'♜','b':'♝','n':'♞','p':'♟',' ':' '}
TAS_PUANLARI = {'P': 1, 'N': 3, 'B': 3, 'R': 5, 'Q': 9, 'K': 0}

beyaz_sirasi = True
beyaz_sah_oynadi = False
beyaz_kale_sol_oynadi = False
beyaz_kale_sag_oynadi = False
siyah_sah_oynadi = False
siyah_kale_sol_oynadi = False
siyah_kale_sag_oynadi = False

gecerken_alinabilir_kare = None
elli_hamle_sayaci = 0
konum_gecmisi = {}
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
# 2. VERİTABANI VE ŞİFRELEME
# =====================================================================
DB_ANAHTAR = "GOALTECH_GIZLI"

def xor_kripto(metin, anahtar):
    metin_str = str(metin)
    return "".join(chr(ord(c) ^ ord(anahtar[i % len(anahtar)])) for i, c in enumerate(metin_str))

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
        baglanti = sqlite3.connect("goaltech_chess.db")
        imlec = baglanti.cursor()
        imlec.execute("INSERT INTO Mac_Gecmisi (oyuncu, beyaz_puan, siyah_puan, kazanan) VALUES (?, ?, ?, ?)", 
                      (xor_kripto(oyuncu_adi, DB_ANAHTAR), xor_kripto(b_skor, DB_ANAHTAR), xor_kripto(s_skor, DB_ANAHTAR), xor_kripto(kazanan_taraf, DB_ANAHTAR)))
        baglanti.commit()
        baglanti.close()
    except Exception as e:
        print("DB HATA:", e)

veritabanini_kur()

def token_uret(kullanici_adi):
    payload = {"oyuncu": kullanici_adi, "oyun": "Goaltech Chess", "exp": int(time.time()) + 3600}
    res = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
    return res if isinstance(res, str) else res.decode('utf-8')

# =====================================================================
# 3. KUSURSUZ SATRANÇ KURAL MOTORU (ROK & BERABERLİK DÜZELTİLMİŞ)
# =====================================================================
def yol_acik_mi(b_sat, b_sut, h_sat, h_sut):
    adim_sat = 0 if h_sat == b_sat else (1 if h_sat > b_sat else -1)
    adim_sut = 0 if h_sut == b_sut else (1 if h_sut > b_sut else -1)
    g_sat, g_sut = b_sat + adim_sat, b_sut + adim_sut
    while (g_sat, g_sut) != (h_sat, h_sut):
        if tahta[g_sat][g_sut] != ' ': return False
        g_sat += adim_sat; g_sut += adim_sut
    return True

def sah_konumu_bul(beyaz_mi):
    aranan_sah = 'K' if beyaz_mi else 'k'
    for r in range(8):
        for c in range(8):
            if tahta[r][c] == aranan_sah: return r, c
    return -1, -1

def tehdit_altinda_mi(satir, sutun, saldirgan_beyaz_mi):
    for r in range(8):
        for c in range(8):
            tas = tahta[r][c]
            if tas != ' ' and (tas.isupper() == saldirgan_beyaz_mi):
                tip = tas.upper()
                df_sat, df_sut = abs(satir - r), abs(sutun - c)
                if tip == 'P':
                    yon = -1 if saldirgan_beyaz_mi else 1
                    if (satir - r == yon) and (df_sut == 1):
                        return True
                elif tip == 'N':
                    if (df_sat == 2 and df_sut == 1) or (df_sat == 1 and df_sut == 2):
                        return True
                elif tip == 'B':
                    if (df_sat == df_sut) and yol_acik_mi(r, c, satir, sutun):
                        return True
                elif tip == 'R':
                    if (r == satir or c == sutun) and yol_acik_mi(r, c, satir, sutun):
                        return True
                elif tip == 'Q':
                    if (r == satir or c == sutun or df_sat == df_sut) and yol_acik_mi(r, c, satir, sutun):
                        return True
                elif tip == 'K':
                    if df_sat <= 1 and df_sut <= 1:
                        return True
    return False

def kural_kontrol(tas, b_sat, b_sut, h_sat, h_sut):
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
        if df_sut == 1 and h_sat - b_sat == yon and hedef == ' ' and gecerken_alinabilir_kare == (h_sat, h_sut): return True
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
        if df_sat <= 1 and df_sut <= 1:
            return True
        # ROK KONTROLLERİ (KUSURSUZ DOĞRULAMA)
        if df_sat == 0 and df_sut == 2:
            if beyaz_mi and (b_sat, b_sut) == (7, 4):
                if beyaz_sah_oynadi or tehdit_altinda_mi(7, 4, False): return False
                # Kısa Rok (g1)
                if h_sut == 6:
                    if beyaz_kale_sag_oynadi or tahta[7][7] != 'R': return False
                    if tahta[7][5] != ' ' or tahta[7][6] != ' ': return False
                    if tehdit_altinda_mi(7, 5, False) or tehdit_altinda_mi(7, 6, False): return False
                    return True
                # Uzun Rok (c1)
                elif h_sut == 2:
                    if beyaz_kale_sol_oynadi or tahta[7][0] != 'R': return False
                    if tahta[7][1] != ' ' or tahta[7][2] != ' ' or tahta[7][3] != ' ': return False
                    if tehdit_altinda_mi(7, 3, False) or tehdit_altinda_mi(7, 2, False): return False
                    return True
            elif not beyaz_mi and (b_sat, b_sut) == (0, 4):
                if siyah_sah_oynadi or tehdit_altinda_mi(0, 4, True): return False
                # Kısa Rok (g8)
                if h_sut == 6:
                    if siyah_kale_sag_oynadi or tahta[0][7] != 'r': return False
                    if tahta[0][5] != ' ' or tahta[0][6] != ' ': return False
                    if tehdit_altinda_mi(0, 5, True) or tehdit_altinda_mi(0, 6, True): return False
                    return True
                # Uzun Rok (c8)
                elif h_sut == 2:
                    if siyah_kale_sol_oynadi or tahta[0][0] != 'r': return False
                    if tahta[0][1] != ' ' or tahta[0][2] != ' ' or tahta[0][3] != ' ': return False
                    if tehdit_altinda_mi(0, 3, True) or tehdit_altinda_mi(0, 2, True): return False
                    return True
        return False

    return False

def gecerli_hamleleri_bul(b_sat, b_sut, b_sirasi):
    secilen = tahta[b_sat][b_sut]
    hamleler = []
    for h_sat in range(8):
        for h_sut in range(8):
            hedef = tahta[h_sat][h_sut]
            if hedef == ' ' or (hedef.isupper() != b_sirasi):
                if kural_kontrol(secilen, b_sat, b_sut, h_sat, h_sut):
                    # Hamleyi sanal uygula
                    alinan_ep = ' '
                    ep_yapiliyor = False
                    if secilen.upper() == 'P' and abs(h_sut - b_sut) == 1 and hedef == ' ':
                        ep_yapiliyor = True
                        yon = -1 if b_sirasi else 1
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
                    
                    s_sat, s_sut = sah_konumu_bul(b_sirasi)
                    if not tehdit_altinda_mi(s_sat, s_sut, not b_sirasi):
                        hamleler.append([h_sat, h_sut])

                    # Geri al (restore)
                    if roklu:
                        tahta[k_eski[0]][k_eski[1]] = tahta[k_yeni[0]][k_yeni[1]]
                        tahta[k_yeni[0]][k_yeni[1]] = ' '
                    if ep_yapiliyor:
                        tahta[h_sat - (-1 if b_sirasi else 1)][h_sut] = alinan_ep
                    tahta[b_sat][b_sut] = secilen
                    tahta[h_sat][h_sut] = hedef
    return hamleler

def tum_gecerli_hamlelerin_sayisi(b_sirasi):
    return sum(len(gecerli_hamleleri_bul(r, c, b_sirasi)) for r in range(8) for c in range(8) if tahta[r][c] != ' ' and tahta[r][c].isupper() == b_sirasi)

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
    if len(taslar) == 0: return True
    if len(taslar) == 1 and taslar[0] in ['N', 'B']: return True
    if len(taslar) == 2 and taslar == ['B', 'B'] and fil_renkleri[0] == fil_renkleri[1]: return True
    return False

def tahta_durum_anahtari(b_sirasi):
    return "".join("".join(s) for s in tahta) + f"_{b_sirasi}_{beyaz_sah_oynadi}{beyaz_kale_sol_oynadi}{beyaz_kale_sag_oynadi}{siyah_sah_oynadi}{siyah_kale_sol_oynadi}{siyah_kale_sag_oynadi}_{gecerken_alinabilir_kare}"

def oyunu_sifirla():
    global tahta, beyaz_skor, siyah_skor, beyaz_sirasi, hamle_gecmisi, konum_gecmisi
    global beyaz_sah_oynadi, beyaz_kale_sol_oynadi, beyaz_kale_sag_oynadi, siyah_sah_oynadi, siyah_kale_sol_oynadi, siyah_kale_sag_oynadi, gecerken_alinabilir_kare, elli_hamle_sayaci, yenilen_beyazlar, yenilen_siyahlar
    tahta = [['r','n','b','q','k','b','n','r'],['p','p','p','p','p','p','p','p'],[' ',' ',' ',' ',' ',' ',' ',' '],[' ',' ',' ',' ',' ',' ',' ',' '],[' ',' ',' ',' ',' ',' ',' ',' '],[' ',' ',' ',' ',' ',' ',' ',' '],['P','P','P','P','P','P','P','P'],['R','N','B','Q','K','B','N','R']]
    beyaz_skor = siyah_skor = 0; yenilen_beyazlar.clear(); yenilen_siyahlar.clear(); hamle_gecmisi.clear(); konum_gecmisi.clear()
    beyaz_sirasi = True; beyaz_sah_oynadi = beyaz_kale_sol_oynadi = beyaz_kale_sag_oynadi = siyah_sah_oynadi = siyah_kale_sol_oynadi = siyah_kale_sag_oynadi = False; gecerken_alinabilir_kare = None; elli_hamle_sayaci = 0
    konum_gecmisi[tahta_durum_anahtari(True)] = 1

# =====================================================================
# 4. FLASK WEB ARAYÜZÜ
# =====================================================================
HTML_PAGE = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Goaltech Chess</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #12161c; color: #fff; margin: 0; padding: 0; min-height: 100vh; overflow: hidden; }
        
        #login-screen { position: absolute; top:0; left:0; width:100%; height:100%; display: flex; flex-direction: column; align-items: center; justify-content: center; z-index: 100; background: radial-gradient(circle at center, #1e242d 0%, #12161c 100%); }
        .login-box { background: rgba(30, 36, 46, 0.85); backdrop-filter: blur(10px); padding: 40px; border-radius: 18px; border: 2px solid #374155; text-align: center; box-shadow: 0 25px 50px rgba(0,0,0,0.5); z-index: 10; width: 320px; }
        .login-box h1 { margin: 0 0 5px; color: #fff; font-size: 32px; letter-spacing: 1px; }
        .login-box p { color: #8c96a5; font-size: 14px; margin-bottom: 25px; }
        .input-group { margin-bottom: 20px; text-align: left; }
        .input-group label { display: block; font-size: 12px; font-weight: bold; color: #8c96a5; margin-bottom: 5px; }
        .input-group input { width: 100%; padding: 12px; border-radius: 8px; border: 2px solid #414b56; background: #141920; color: #fff; font-size: 16px; outline: none; box-sizing: border-box; transition: border 0.3s; }
        .input-group input:focus { border-color: #00b4c8; }
        .login-btn { background: #ea7314; color: white; border: none; padding: 15px; width: 100%; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer; transition: 0.2s; }
        .login-btn:hover { background: #c25b0b; }
        #login-err { color: #ff4b4b; margin-top: 15px; font-weight: bold; font-size: 14px; }
        
        .bg-piece { position: absolute; opacity: 0.05; filter: blur(2px); pointer-events: none; animation: float 15s infinite ease-in-out alternate; }
        @keyframes float { 0% { transform: translateY(0) rotate(0deg); } 100% { transform: translateY(-100px) rotate(20deg); } }

        #game-screen { display: none; flex-direction: column; align-items: center; justify-content: flex-start; padding: 20px; height: 100vh; overflow-y: auto; box-sizing: border-box; }
        .panels { display: flex; gap: 20px; margin-bottom: 15px; width: 100%; max-width: 520px; justify-content: space-between; }
        .score-box { background: #1e242d; padding: 10px 15px; border-radius: 8px; flex: 1; border: 1px solid #333; }
        .score-box h3 { margin: 0 0 5px 0; font-size: 16px; color: #facc15; }
        .caps { font-size: 22px; color: #888; }
        
        .board { display: grid; grid-template-columns: repeat(8, 62px); grid-template-rows: repeat(8, 62px); border: 4px solid #27303f; border-radius: 8px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); user-select: none; position: relative; }
        @media (max-width: 530px) { .board { grid-template-columns: repeat(8, 44px); grid-template-rows: repeat(8, 44px); } .square img { width: 36px!important; height: 36px!important; } }
        
        .square { display: flex; align-items: center; justify-content: center; cursor: pointer; position: relative; transition: background 0.1s; }
        .square img { width: 50px; height: 50px; pointer-events: none; z-index: 5; filter: drop-shadow(0px 3px 2px rgba(0,0,0,0.4)); }
        .light { background-color: #ebecd0; }
        .dark { background-color: #414b56; }
        .selected { background-color: #facc15 !important; }
        .in-check { background-color: #ef4444 !important; }
        .valid-dot { width: 22px; height: 22px; background-color: rgba(34, 197, 94, 0.85); border-radius: 50%; position: absolute; z-index: 10; box-shadow: 0 0 8px rgba(0,0,0,0.6); pointer-events: none; }
        
        .controls { margin-top: 20px; display: flex; gap: 10px; }
        .btn { padding: 12px 20px; font-weight: bold; font-size: 15px; border: none; border-radius: 6px; cursor: pointer; color: white; transition: 0.2s; }
        .btn-undo { background: #059669; } .btn-undo:hover { background: #047857; }
        .btn-reset { background: #2563eb; } .btn-reset:hover { background: #1d4ed8; }
        .btn-logout { background: #be123c; margin-left: 20px; } .btn-logout:hover { background: #9f1239; }
        
        #msg { margin-top: 15px; font-weight: bold; color: #f87171; font-size: 20px; text-shadow: 0 2px 4px rgba(0,0,0,0.5); }
        .token-bar { margin-top: auto; margin-bottom: 10px; background: #1a1f26; padding: 10px 20px; border-radius: 8px; font-size: 12px; color: #6b7280; font-family: monospace; border: 1px dashed #374151; word-break: break-all; max-width: 520px; text-align: center; }
        .token-bar strong { color: #10b981; }

        /* TERFİ SEÇİM MODALI */
        #promo-modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.7); z-index: 200; align-items: center; justify-content: center; }
        .promo-content { background: #1e242d; padding: 20px; border-radius: 12px; border: 2px solid #facc15; text-align: center; }
        .promo-pieces { display: flex; gap: 15px; margin-top: 15px; }
        .promo-piece { background: #2d3748; padding: 10px; border-radius: 8px; cursor: pointer; transition: 0.2s; }
        .promo-piece:hover { background: #4a5568; transform: scale(1.1); }
        .promo-piece img { width: 50px; height: 50px; }
    </style>
</head>
<body>

    <div id="login-screen">
        <img src="https://upload.wikimedia.org/wikipedia/commons/f/f0/Chess_kdt45.svg" class="bg-piece" style="top: 10%; left: 10%; width: 150px; animation-delay: 0s;">
        <img src="https://upload.wikimedia.org/wikipedia/commons/4/42/Chess_klt45.svg" class="bg-piece" style="top: 60%; right: 10%; width: 120px; animation-delay: 2s;">
        <img src="https://upload.wikimedia.org/wikipedia/commons/7/70/Chess_nlt45.svg" class="bg-piece" style="top: 20%; right: 20%; width: 100px; animation-delay: 1s;">
        <img src="https://upload.wikimedia.org/wikipedia/commons/e/ef/Chess_ndt45.svg" class="bg-piece" style="bottom: 10%; left: 20%; width: 130px; animation-delay: 3s;">

        <div class="login-box">
            <h1>GOALTECH</h1>
            <p>Güvenli Oyuncu Giriş Portalı</p>
            <div class="input-group">
                <label>KULLANICI ADI</label>
                <input type="text" id="username" value="vahit">
            </div>
            <div class="input-group">
                <label>ŞİFRE</label>
                <input type="password" id="password">
            </div>
            <button class="login-btn" onclick="doLogin()">OYUNA GİRİŞ YAP ➔</button>
            <div id="login-err"></div>
        </div>
    </div>

    <div id="game-screen">
        <h1 style="margin:0 0 10px 0; color: #fff;">GOALTECH <span style="color:#4ade80;">CHESS</span></h1>
        
        <div class="panels">
            <div class="score-box">
                <h3>Beyaz Puan: <span id="w-score">0</span></h3>
                <div class="caps" id="w-caps"></div>
            </div>
            <div class="score-box">
                <h3>Siyah Puan: <span id="b-score">0</span></h3>
                <div class="caps" id="b-caps"></div>
            </div>
        </div>

        <div class="board" id="board"></div>
        <div id="msg"></div>
        
        <div class="controls">
            <button class="btn btn-undo" onclick="undoGame()">↩ Geri Al</button>
            <button class="btn btn-reset" onclick="resetGame()">Yeni Oyun</button>
            <button class="btn btn-logout" onclick="logout()">Çıkış (ESC)</button>
        </div>

        <div class="token-bar">
            <strong>Aktif JWT Token:</strong> <span id="token-disp"></span>
        </div>
    </div>

    <div id="promo-modal">
        <div class="promo-content">
            <h3 style="margin:0; color:#facc15;">Terfi Edecek Taşı Seçin</h3>
            <div class="promo-pieces" id="promo-options"></div>
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

        let token = localStorage.getItem('goaltech_token');
        let boardState = [], selected = null, validMoves = [], whiteTurn = true, isCheck = false;
        let isProcessing = false;
        let pendingMove = null;

        if (token) showGame();

        async function doLogin() {
            const u = document.getElementById('username').value;
            const p = document.getElementById('password').value;
            const res = await fetch('/api/login', {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({username: u, password: p})
            });
            const data = await res.json();
            if (data.success) {
                token = data.token;
                localStorage.setItem('goaltech_token', token);
                document.getElementById('login-err').innerText = '';
                showGame();
            } else {
                document.getElementById('login-err').innerText = data.error;
            }
        }

        function logout() {
            token = null;
            localStorage.removeItem('goaltech_token');
            document.getElementById('game-screen').style.display = 'none';
            document.getElementById('login-screen').style.display = 'flex';
            document.getElementById('password').value = '';
        }

        function showGame() {
            document.getElementById('login-screen').style.display = 'none';
            document.getElementById('game-screen').style.display = 'flex';
            document.getElementById('token-disp').innerText = token.substring(0, 40) + '...';
            fetchState();
        }

        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && token) logout();
            if (e.key === 'Enter' && !token) doLogin();
        });

        async function fetchState() {
            const res = await fetch('/api/state', { headers: {'Authorization': 'Bearer ' + token} });
            const data = await res.json();
            boardState = data.tahta; whiteTurn = data.beyaz_sirasi; isCheck = data.sah_tehdit;
            document.getElementById('w-score').innerText = data.b_skor;
            document.getElementById('w-caps').innerText = data.y_siyah.join(' ');
            document.getElementById('b-score').innerText = data.s_skor;
            document.getElementById('b-caps').innerText = data.y_beyaz.join(' ');
            render();
        }

        function render() {
            const bEl = document.getElementById('board'); bEl.innerHTML = '';
            for (let r = 0; r < 8; r++) {
                for (let c = 0; c < 8; c++) {
                    const sq = document.createElement('div');
                    sq.className = 'square ' + ((r + c) % 2 === 0 ? 'light' : 'dark');
                    const piece = boardState[r][c];
                    
                    if (piece !== ' ') {
                        const img = document.createElement('img');
                        img.src = IMAGES[piece];
                        sq.appendChild(img);
                    }

                    if (selected && selected[0] === r && selected[1] === c) sq.classList.add('selected');
                    if (isCheck && ((whiteTurn && piece === 'K') || (!whiteTurn && piece === 'k'))) sq.classList.add('in-check');
                    if (validMoves.some(m => m[0] === r && m[1] === c)) {
                        const dot = document.createElement('div'); dot.className = 'valid-dot'; sq.appendChild(dot);
                    }
                    sq.onmousedown = (e) => { e.preventDefault(); onSquareClick(r, c); };
                    bEl.appendChild(sq);
                }
            }
        }

        function showPromoModal(from, to) {
            pendingMove = { from, to };
            const modal = document.getElementById('promo-modal');
            const opts = document.getElementById('promo-options');
            opts.innerHTML = '';
            const pieces = whiteTurn ? ['Q', 'R', 'B', 'N'] : ['q', 'r', 'b', 'n'];
            pieces.forEach(p => {
                const item = document.createElement('div');
                item.className = 'promo-piece';
                item.innerHTML = `<img src="${IMAGES[p]}">`;
                item.onclick = () => selectPromotion(p);
                opts.appendChild(item);
            });
            modal.style.display = 'flex';
        }

        async function selectPromotion(pieceChoice) {
            document.getElementById('promo-modal').style.display = 'none';
            if (!pendingMove) return;
            await sendMove(pendingMove.from, pendingMove.to, pieceChoice);
            pendingMove = null;
        }

        async function sendMove(from, to, promo = null) {
            isProcessing = true;
            const res = await fetch('/api/move', {
                method: 'POST', headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token},
                body: JSON.stringify({ from: from, to: to, promotion: promo })
            });
            const data = await res.json();
            if (data.success) {
                selected = null; validMoves = [];
                await fetchState();
                if (data.mesaj) document.getElementById('msg').innerText = data.mesaj;
            } else {
                document.getElementById('msg').innerText = data.error;
            }
            isProcessing = false;
        }

        async function onSquareClick(r, c) {
            if (isProcessing) return;
            document.getElementById('msg').innerText = '';
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
            
            if ((whiteTurn && isWhitePiece) || (!whiteTurn && isBlackPiece)) {
                selected = [r, c];
                isProcessing = true;
                const res = await fetch('/api/valid_moves', {
                    method: 'POST', headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token},
                    body: JSON.stringify({ r, c })
                });
                const data = await res.json();
                validMoves = data.moves || [];
                render();
                isProcessing = false;
            } else {
                selected = null; validMoves = []; render();
            }
        }

        async function undoGame() { if(isProcessing) return; isProcessing=true; await fetch('/api/undo', { method: 'POST', headers: {'Authorization': 'Bearer ' + token} }); selected = null; validMoves = []; document.getElementById('msg').innerText = ''; await fetchState(); isProcessing=false; }
        async function resetGame() { if(isProcessing) return; isProcessing=true; await fetch('/api/reset', { method: 'POST', headers: {'Authorization': 'Bearer ' + token} }); selected = null; validMoves = []; document.getElementById('msg').innerText = ''; await fetchState(); isProcessing=false; }
    </script>
</body>
</html>"""

@app.route('/')
def home():
    return HTML_PAGE

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.json or {}
    u, p = data.get('username'), data.get('password')
    if u == KAYITLI_KULLANICI and p == KAYITLI_SIFRE:
        return jsonify({'success': True, 'token': token_uret(u)})
    return jsonify({'success': False, 'error': 'Hatalı kullanıcı adı veya şifre!'})

@app.route('/api/state')
def api_state():
    k_sat, k_sut = sah_konumu_bul(beyaz_sirasi)
    sah_tehdidi = tehdit_altinda_mi(k_sat, k_sut, not beyaz_sirasi) if k_sat != -1 else False
    return jsonify({'tahta': tahta, 'beyaz_sirasi': beyaz_sirasi, 'sah_tehdit': sah_tehdidi, 'b_skor': beyaz_skor, 's_skor': siyah_skor, 'y_beyaz': yenilen_beyazlar, 'y_siyah': yenilen_siyahlar})

@app.route('/api/valid_moves', methods=['POST'])
def api_valid():
    req = request.json or {}
    return jsonify({'moves': gecerli_hamleleri_bul(req.get('r'), req.get('c'), beyaz_sirasi)})

@app.route('/api/undo', methods=['POST'])
def api_undo():
    global tahta, beyaz_sirasi, beyaz_skor, siyah_skor, yenilen_beyazlar, yenilen_siyahlar, beyaz_sah_oynadi, beyaz_kale_sol_oynadi, beyaz_kale_sag_oynadi, siyah_sah_oynadi, siyah_kale_sol_oynadi, siyah_kale_sag_oynadi, gecerken_alinabilir_kare, elli_hamle_sayaci, hamle_gecmisi
    if hamle_gecmisi:
        eski = hamle_gecmisi.pop()
        tahta = eski['tahta']; beyaz_sirasi = eski['sira']
        beyaz_skor = eski['b_skor']; siyah_skor = eski['s_skor']
        yenilen_beyazlar = list(eski['y_beyaz']); yenilen_siyahlar = list(eski['y_siyah'])
        beyaz_sah_oynadi = eski['b_sah']; siyah_sah_oynadi = eski['s_sah']
        beyaz_kale_sol_oynadi = eski['b_k_sol']; beyaz_kale_sag_oynadi = eski['b_k_sag']
        siyah_kale_sol_oynadi = eski['s_k_sol']; siyah_kale_sag_oynadi = eski['s_k_sag']
        gecerken_alinabilir_kare = eski['gecerken']; elli_hamle_sayaci = eski['elli_sayac']
    return jsonify({'success': True})

@app.route('/api/move', methods=['POST'])
def api_move():
    global tahta, beyaz_sirasi, beyaz_skor, siyah_skor, yenilen_beyazlar, yenilen_siyahlar, beyaz_sah_oynadi, beyaz_kale_sol_oynadi, beyaz_kale_sag_oynadi, siyah_sah_oynadi, siyah_kale_sol_oynadi, siyah_kale_sag_oynadi, gecerken_alinabilir_kare, elli_hamle_sayaci, konum_gecmisi, hamle_gecmisi

    data = request.json or {}
    b_sat, b_sut = data.get('from')
    h_sat, h_sut = data.get('to')
    terfi = data.get('promotion')
    secilen = tahta[b_sat][b_sut]
    hedef = tahta[h_sat][h_sut]
    gecerliler = gecerli_hamleleri_bul(b_sat, b_sut, beyaz_sirasi)
    
    if [h_sat, h_sut] not in gecerliler: return jsonify({'success': False, 'error': 'Kural dışı hamle!'})
        
    hamle_gecmisi.append({
        'tahta': [s[:] for s in tahta], 'sira': beyaz_sirasi, 'b_skor': beyaz_skor, 's_skor': siyah_skor,
        'y_beyaz': list(yenilen_beyazlar), 'y_siyah': list(yenilen_siyahlar),
        'b_sah': beyaz_sah_oynadi, 'b_k_sol': beyaz_kale_sol_oynadi, 'b_k_sag': beyaz_kale_sag_oynadi,
        's_sah': siyah_sah_oynadi, 's_k_sol': siyah_kale_sol_oynadi, 's_k_sag': siyah_kale_sag_oynadi,
        'gecerken': gecerken_alinabilir_kare, 'elli_sayac': elli_hamle_sayaci
    })

    tas_yendi_mi, yeni_gecerken = False, None
    if secilen.upper() == 'P':
        yon = -1 if beyaz_sirasi else 1
        if abs(h_sat - b_sat) == 2: yeni_gecerken = (b_sat + yon, b_sut)
        if abs(h_sut - b_sut) == 1 and hedef == ' ' and gecerken_alinabilir_kare == (h_sat, h_sut):
            alinan = tahta[h_sat - yon][h_sut]; tahta[h_sat - yon][h_sut] = ' '; tas_yendi_mi = True
            if beyaz_sirasi: beyaz_skor += TAS_PUANLARI['P']; yenilen_siyahlar.append(SEMBOLLER[alinan])
            else: siyah_skor += TAS_PUANLARI['P']; yenilen_beyazlar.append(SEMBOLLER[alinan])

    gecerken_alinabilir_kare = yeni_gecerken
    if hedef != ' ':
        tas_yendi_mi = True; puan = TAS_PUANLARI.get(hedef.upper(), 0)
        if beyaz_sirasi: beyaz_skor += puan; yenilen_siyahlar.append(SEMBOLLER[hedef])
        else: siyah_skor += puan; yenilen_beyazlar.append(SEMBOLLER[hedef])

    elli_hamle_sayaci = 0 if (secilen.upper() == 'P' or tas_yendi_mi) else elli_hamle_sayaci + 1

    # ROK ATILDIĞINDA KALEYİ DOĞRU KAREYE TAŞI
    if secilen.upper() == 'K' and abs(h_sut - b_sut) == 2:
        if h_sut == 6: # Kısa Rok
            tahta[h_sat][5] = tahta[h_sat][7]; tahta[h_sat][7] = ' '
        elif h_sut == 2: # Uzun Rok
            tahta[h_sat][3] = tahta[h_sat][0]; tahta[h_sat][0] = ' '

    # TAŞI YERLEŞTİR VE TERFİ KONTROLÜ
    if secilen.upper() == 'P' and terfi:
        tahta[h_sat][h_sut] = terfi.upper() if beyaz_sirasi else terfi.lower()
    else:
        tahta[h_sat][h_sut] = secilen
    tahta[b_sat][b_sut] = ' '

    # OYNAMA BAYRAKLARI
    if secilen == 'K': beyaz_sah_oynadi = True
    elif secilen == 'k': siyah_sah_oynadi = True
    elif secilen == 'R':
        if (b_sat, b_sut) == (7, 0): beyaz_kale_sol_oynadi = True
        elif (b_sat, b_sut) == (7, 7): beyaz_kale_sag_oynadi = True
    elif secilen == 'r':
        if (b_sat, b_sut) == (0, 0): siyah_kale_sol_oynadi = True
        elif (b_sat, b_sut) == (0, 7): siyah_kale_sag_oynadi = True

    beyaz_sirasi = not beyaz_sirasi
    anahtar = tahta_durum_anahtari(beyaz_sirasi)
    konum_gecmisi[anahtar] = konum_gecmisi.get(anahtar, 0) + 1

    sah_r, sah_c = sah_konumu_bul(beyaz_sirasi)
    sah_tehdidi = tehdit_altinda_mi(sah_r, sah_c, not beyaz_sirasi) if sah_r != -1 else False
    kalan = tum_gecerli_hamlelerin_sayisi(beyaz_sirasi)

    mesaj = ""
    if kalan == 0:
        if sah_tehdidi:
            mesaj = f"ŞAH MAT! {'Siyah' if not beyaz_sirasi else 'Beyaz'} Kazandı!"
            mac_kaydet("vahit", beyaz_skor, siyah_skor, 'Siyah' if not beyaz_sirasi else 'Beyaz')
        else:
            mesaj = "PAT! Oyun Berabere."
            mac_kaydet("vahit", beyaz_skor, siyah_skor, "BERABERE")
    elif elli_hamle_sayaci >= 100:
        mesaj = "50 Hamle Kuralı Sebebiyle Berabere!"
        mac_kaydet("vahit", beyaz_skor, siyah_skor, "BERABERE")
    elif konum_gecmisi.get(anahtar, 0) >= 3:
        mesaj = "3 Kez Konum Tekrarı Sebebiyle Berabere!"
        mac_kaydet("vahit", beyaz_skor, siyah_skor, "BERABERE")
    elif yetersiz_materyal_mi():
        mesaj = "Yetersiz Materyal Sebebiyle Berabere!"
        mac_kaydet("vahit", beyaz_skor, siyah_skor, "BERABERE")
    
    return jsonify({'success': True, 'mesaj': mesaj})

@app.route('/api/reset', methods=['POST'])
def api_reset():
    oyunu_sifirla()
    return jsonify({'success': True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
