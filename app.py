import os
import time
import sqlite3
import jwt
from flask import Flask, jsonify, request

app = Flask(__name__)

# =====================================================================
# 1. GÜVENLİK, TOKEN VE VERİTABANI
# =====================================================================
KAYITLI_KULLANICI = "vahit"
KAYITLI_SIFRE = "yasin12345"
SECRET_KEY = "goaltech_secret_key"
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
    payload = {"oyuncu": kullanici_adi, "oyun": "Goaltech Chess", "exp": int(time.time()) + 7200}
    res = jwt.encode(payload, SECRET_KEY, algorithm="HS256")
    return res if isinstance(res, str) else res.decode('utf-8')

# =====================================================================
# 2. ODA YÖNETİMİ VE TÜM OYUN VERİLERİ
# =====================================================================
SEMBOLLER = {'K':'♔','Q':'♕','R':'♖','B':'♗','N':'♘','P':'♙', 'k':'♚','q':'♛','r':'♜','b':'♝','n':'♞','p':'♟',' ':' '}
TAS_PUANLARI = {'P': 1, 'N': 3, 'B': 3, 'R': 5, 'Q': 9, 'K': 0}

odalar = {}

def tahta_durum_anahtari(oda):
    t_str = "".join("".join(s) for s in oda['tahta'])
    r_str = f"{oda['b_sah']}{oda['b_k_sol']}{oda['b_k_sag']}{oda['s_sah']}{oda['s_k_sol']}{oda['s_k_sag']}"
    return f"{t_str}_{oda['beyaz_sirasi']}_{r_str}_{oda['gecerken']}"

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
        'mesaj': '',
        'secili_dakika': sure_dakika,
        'beyaz_sure': sure_dakika * 60,
        'siyah_sure': sure_dakika * 60,
        'son_zaman': time.time(),
        'oyun_basladi': False
    }
    oda['konum_gecmisi'][tahta_durum_anahtari(oda)] = 1
    return oda

def sure_guncelle(oda):
    if not oda['oyun_basladi']:
        oda['son_zaman'] = time.time()
        return

    simdi = time.time()
    gecen = simdi - oda['son_zaman']
    oda['son_zaman'] = simdi

    if oda['beyaz_sirasi']:
        oda['beyaz_sure'] = max(0, oda['beyaz_sure'] - gecen)
        if oda['beyaz_sure'] == 0:
            oda['beyaz_sirasi'] = False
            oda['beyaz_sure'] = oda['secili_dakika'] * 60
            oda['mesaj'] = "Beyazın süresi bitti! Sıra Siyaha geçti."
    else:
        oda['siyah_sure'] = max(0, oda['siyah_sure'] - gecen)
        if oda['siyah_sure'] == 0:
            oda['beyaz_sirasi'] = True
            oda['siyah_sure'] = oda['secili_dakika'] * 60
            oda['mesaj'] = "Siyahın süresi bitti! Sıra Beyaza geçti."

# =====================================================================
# 3. KURAL MOTORU (ROK, EN PASSANT, BERABERLİKLER)
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
    hamleler = []
    for h_sat in range(8):
        for h_sut in range(8):
            hedef = tahta[h_sat][h_sut]
            if hedef == ' ' or (hedef.isupper() != b_sirasi):
                if kural_kontrol(oda, secilen, b_sat, b_sut, h_sat, h_sut):
                    alinan_ep = ' '
                    ep = False
                    if secilen.upper() == 'P' and abs(h_sut - b_sut) == 1 and hedef == ' ':
                        ep = True
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
                    
                    s_sat, s_sut = sah_konumu_bul(tahta, b_sirasi)
                    if not tehdit_altinda_mi(tahta, s_sat, s_sut, not b_sirasi):
                        hamleler.append([h_sat, h_sut])

                    if roklu:
                        tahta[k_eski[0]][k_eski[1]] = tahta[k_yeni[0]][k_yeni[1]]
                        tahta[k_yeni[0]][k_yeni[1]] = ' '
                    if ep:
                        tahta[h_sat - (-1 if b_sirasi else 1)][h_sut] = alinan_ep
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
    if len(taslar) == 2 and taslar == ['B', 'B'] and fil_renkleri[0] == fil_renkleri[1]: return True
    return False

# =====================================================================
# 4. MODERN ARAYÜZ (GİRİŞ KAPISI + TOKEN ROZETİ + OYUN)
# =====================================================================
HTML_PAGE = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Goaltech Chess Online</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800&family=JetBrains+Mono:wght@600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0f17;
            --card-bg: rgba(22, 29, 43, 0.75);
            --card-border: rgba(255, 255, 255, 0.08);
            --primary: #3b82f6;
            --accent: #10b981;
            --gold: #f59e0b;
        }
        * { box-sizing: border-box; font-family: 'Outfit', sans-serif; }
        body { background: var(--bg-color); color: #fff; margin: 0; padding: 0; min-height: 100vh; overflow-x: hidden; background-image: radial-gradient(circle at 50% 0%, #1e293b 0%, #0b0f17 75%); }

        /* GİRİŞ EKRANI */
        #login-screen { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center; z-index: 100; backdrop-filter: blur(14px); background: rgba(11, 15, 23, 0.85); }
        .login-box { background: var(--card-bg); border: 1px solid var(--card-border); padding: 36px; border-radius: 24px; text-align: center; width: 340px; box-shadow: 0 20px 50px rgba(0,0,0,0.6); }
        .login-box h1 { margin: 0 0 4px; font-size: 30px; font-weight: 800; letter-spacing: -1px; }
        .login-box p { color: #64748b; font-size: 13px; margin-bottom: 22px; font-weight: 600; }
        .input-group { margin-bottom: 14px; text-align: left; }
        .input-group label { display: block; font-size: 11px; font-weight: 700; color: #94a3b8; text-transform: uppercase; margin-bottom: 6px; letter-spacing: 0.5px; }
        .input-group input { width: 100%; padding: 12px 14px; border-radius: 12px; border: 1px solid var(--card-border); background: rgba(11, 15, 23, 0.6); color: #fff; font-size: 15px; outline: none; transition: 0.2s; }
        .input-group input:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2); }
        .btn-main { width: 100%; padding: 13px; background: linear-gradient(135deg, #2563eb, #1d4ed8); border: none; border-radius: 12px; color: #fff; font-size: 15px; font-weight: 700; cursor: pointer; transition: 0.2s; box-shadow: 0 10px 20px rgba(37, 99, 235, 0.3); }
        .btn-main:hover { transform: translateY(-2px); }

        /* OYUN ALANI */
        #game-screen { display: none; flex-direction: column; align-items: center; padding: 16px 10px; max-width: 600px; margin: 0 auto; }
        
        .top-bar { width: 100%; display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; background: var(--card-bg); padding: 10px 16px; border-radius: 16px; border: 1px solid var(--card-border); }
        .logo-title { font-size: 20px; font-weight: 800; letter-spacing: -0.5px; }
        .logo-title span { color: var(--accent); }
        .role-badge { font-size: 12px; padding: 4px 10px; border-radius: 20px; font-weight: 700; background: rgba(255,255,255,0.06); border: 1px solid var(--card-border); }

        .time-picker-bar { width: 100%; display: flex; align-items: center; justify-content: space-between; background: var(--card-bg); border: 1px solid var(--card-border); padding: 8px 14px; border-radius: 14px; margin-bottom: 12px; }
        .time-label { font-size: 12px; font-weight: 700; color: #94a3b8; text-transform: uppercase; }
        .time-options { display: flex; gap: 6px; }
        .time-btn { background: rgba(255,255,255,0.05); border: 1px solid var(--card-border); color: #cbd5e1; padding: 6px 12px; border-radius: 8px; font-size: 12px; font-weight: 700; cursor: pointer; transition: 0.2s; }
        .time-btn:hover { background: rgba(255,255,255,0.15); }
        .time-btn.active { background: var(--primary); color: white; border-color: var(--primary); }

        .status-container { width: 100%; display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
        .score-card { background: var(--card-bg); border: 1px solid var(--card-border); padding: 12px; border-radius: 14px; display: flex; flex-direction: column; justify-content: space-between; }
        .score-card.active-turn { border-color: var(--gold); box-shadow: 0 0 15px rgba(245, 158, 11, 0.15); }
        .card-header { display: flex; justify-content: space-between; align-items: center; }
        .score-card .title { font-size: 12px; font-weight: 700; color: #94a3b8; text-transform: uppercase; }
        .clock-display { font-family: 'JetBrains Mono', monospace; font-size: 22px; font-weight: 700; color: #f8fafc; }
        .clock-display.danger { color: #ef4444; }
        .caps { font-size: 16px; min-height: 20px; color: #64748b; margin-top: 4px; }

        .board-wrapper { position: relative; padding: 6px; background: #161d2b; border-radius: 16px; box-shadow: 0 20px 40px rgba(0,0,0,0.7); border: 2px solid rgba(255,255,255,0.06); }
        .board { display: grid; grid-template-columns: repeat(8, 62px); grid-template-rows: repeat(8, 62px); border-radius: 10px; overflow: hidden; }
        @media (max-width: 530px) {
            .board { grid-template-columns: repeat(8, 43px); grid-template-rows: repeat(8, 43px); }
            .square img { width: 34px !important; height: 34px !important; }
        }
        .square { display: flex; align-items: center; justify-content: center; cursor: pointer; position: relative; user-select: none; }
        .square img { width: 48px; height: 48px; pointer-events: none; z-index: 5; filter: drop-shadow(0 4px 4px rgba(0,0,0,0.3)); }
        .light { background-color: #e2e8f0; }
        .dark { background-color: #475569; }
        .selected { background-color: #facc15 !important; }
        .in-check { background-color: #ef4444 !important; }
        .valid-dot { width: 18px; height: 18px; background-color: rgba(16, 185, 129, 0.85); border-radius: 50%; position: absolute; z-index: 10; pointer-events: none; }

        .action-grid { width: 100%; display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 12px; }
        .btn-modern { padding: 12px 14px; border-radius: 12px; border: 1px solid var(--card-border); background: var(--card-bg); color: #fff; font-size: 13px; font-weight: 700; cursor: pointer; transition: 0.2s; display: flex; align-items: center; justify-content: center; gap: 6px; }
        .btn-modern:hover { transform: translateY(-2px); }
        .btn-share { background: linear-gradient(135deg, rgba(16, 185, 129, 0.2), rgba(5, 150, 105, 0.2)); border-color: var(--accent); color: #34d399; }
        .btn-undo { background: rgba(59, 130, 246, 0.15); color: #60a5fa; }
        .btn-logout { background: rgba(239, 68, 68, 0.15); color: #f87171; }

        #msg { margin-top: 10px; font-size: 15px; font-weight: 700; color: #f87171; min-height: 22px; text-align: center; }

        /* TOKEN ROZETİ (ŞIK VE SADE) */
        .token-badge { margin-top: 14px; font-size: 11px; color: #64748b; font-family: 'JetBrains Mono', monospace; background: rgba(255,255,255,0.03); border: 1px dashed var(--card-border); padding: 6px 14px; border-radius: 20px; display: flex; align-items: center; gap: 8px; }
        .token-dot { width: 8px; height: 8px; background: #10b981; border-radius: 50%; box-shadow: 0 0 8px #10b981; }

        #toast { position: fixed; bottom: 30px; background: #10b981; color: white; padding: 10px 20px; border-radius: 30px; font-weight: 700; font-size: 13px; opacity: 0; pointer-events: none; transition: 0.3s; z-index: 300; }
        #toast.show { opacity: 1; transform: translateY(-10px); }

        #promo-modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.7); backdrop-filter: blur(8px); z-index: 200; align-items: center; justify-content: center; }
        .promo-content { background: var(--card-bg); border: 1px solid var(--card-border); padding: 24px; border-radius: 20px; text-align: center; }
        .promo-pieces { display: flex; gap: 12px; margin-top: 16px; }
        .promo-piece { background: rgba(255,255,255,0.05); padding: 10px; border-radius: 12px; cursor: pointer; transition: 0.2s; border: 1px solid var(--card-border); }
        .promo-piece:hover { background: rgba(255,255,255,0.15); transform: scale(1.1); }
        .promo-piece img { width: 48px; height: 48px; }
    </style>
</head>
<body>

    <div id="toast">Bağlantı Panoya Kopyalandı! 🚀</div>

    <!-- GİRİŞ PORTALI -->
    <div id="login-screen">
        <div class="login-box">
            <h1>GOALTECH</h1>
            <p>JWT Korumalı Satranç Arenası</p>
            <div class="input-group">
                <label>Kullanıcı Adı</label>
                <input type="text" id="username" value="vahit">
            </div>
            <div class="input-group">
                <label>Şifre</label>
                <input type="password" id="password" value="yasin12345">
            </div>
            <button class="btn-main" onclick="doLogin()">Giriş Yap & Token Al</button>
            <div id="login-err" style="color:#ef4444; font-size:12px; font-weight:700; margin-top:12px;"></div>
        </div>
    </div>

    <!-- OYUN ALANI -->
    <div id="game-screen">
        <div class="top-bar">
            <div class="logo-title">GOALTECH <span>CHESS</span></div>
            <div class="role-badge" id="role-badge">Taraf: Beyaz</div>
        </div>

        <div class="time-picker-bar">
            <span class="time-label">⏱ Süre:</span>
            <div class="time-options">
                <button class="time-btn" onclick="setTimeLimit(1)">1 Dk</button>
                <button class="time-btn active" id="btn-time-3" onclick="setTimeLimit(3)">3 Dk</button>
                <button class="time-btn" onclick="setTimeLimit(5)">5 Dk</button>
                <button class="time-btn" onclick="setTimeLimit(10)">10 Dk</button>
            </div>
        </div>

        <div class="status-container">
            <div class="score-card" id="card-white">
                <div class="card-header">
                    <span class="title">Beyaz (<span id="w-score">0</span>)</span>
                    <span class="clock-display" id="w-clock">03:00</span>
                </div>
                <div class="caps" id="w-caps"></div>
            </div>
            <div class="score-card" id="card-black">
                <div class="card-header">
                    <span class="title">Siyah (<span id="b-score">0</span>)</span>
                    <span class="clock-display" id="b-clock">03:00</span>
                </div>
                <div class="caps" id="b-caps"></div>
            </div>
        </div>

        <div class="board-wrapper">
            <div class="board" id="board"></div>
        </div>

        <div id="msg"></div>

        <div class="action-grid">
            <button class="btn-modern btn-share" onclick="copyInviteLink()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>
                Paylaş
            </button>
            <button class="btn-modern btn-undo" onclick="undoGame()">↩ Geri Al</button>
            <button class="btn-modern btn-logout" onclick="logout()">Çıkış Yap</button>
        </div>

        <!-- DOĞRULANMIŞ TOKEN ROZETİ -->
        <div class="token-badge">
            <span class="token-dot"></span>
            <span>JWT Bilet Doğrulandı: <strong id="token-preview" style="color:#94a3b8;"></strong></span>
        </div>
    </div>

    <div id="promo-modal">
        <div class="promo-content">
            <h3 style="margin:0; font-size:16px;">Terfi Edecek Taşı Seç</h3>
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

        const urlParams = new URLSearchParams(window.location.search);
        let currentRoom = urlParams.get('oda') || 'oda_' + Math.random().toString(36).substring(2, 8);
        let mySide = urlParams.get('oda') ? 'siyah' : 'beyaz';

        let token = localStorage.getItem('goaltech_token');
        let boardState = [], selected = null, validMoves = [], whiteTurn = true, isCheck = false;
        let isProcessing = false;
        let pendingMove = null;
        let pollingTimer = null;

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

        function showGame() {
            document.getElementById('login-screen').style.display = 'none';
            document.getElementById('game-screen').style.display = 'flex';
            document.getElementById('role-badge').innerText = 'Tarafın: ' + (mySide === 'beyaz' ? 'Beyaz ♔' : 'Siyah ♚');
            document.getElementById('token-preview').innerText = token.substring(0, 18) + '...';
            fetchState();
            if (!pollingTimer) pollingTimer = setInterval(fetchState, 1000);
        }

        function formatTime(seconds) {
            const m = Math.floor(seconds / 60);
            const s = Math.floor(seconds % 60);
            return (m < 10 ? '0' : '') + m + ':' + (s < 10 ? '0' : '') + s;
        }

        async function setTimeLimit(mins) {
            await fetch('/api/set_time?oda=' + currentRoom, {
                method: 'POST', headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token},
                body: JSON.stringify({ minutes: mins })
            });
            await fetchState();
        }

        function copyInviteLink() {
            const fullLink = window.location.origin + window.location.pathname + '?oda=' + currentRoom;
            navigator.clipboard.writeText(fullLink).then(() => {
                const toast = document.getElementById('toast');
                toast.classList.add('show');
                setTimeout(() => toast.classList.remove('show'), 2500);
            });
        }

        async function logout() {
            clearInterval(pollingTimer);
            pollingTimer = null;
            await fetch('/api/reset?oda=' + currentRoom, { method: 'POST', headers: {'Authorization': 'Bearer ' + token} });
            token = null;
            localStorage.removeItem('goaltech_token');
            window.location.href = window.location.origin + window.location.pathname;
        }

        async function fetchState() {
            try {
                const res = await fetch('/api/state?oda=' + currentRoom, { headers: {'Authorization': 'Bearer ' + token} });
                if (res.status === 401) { logout(); return; }
                const data = await res.json();
                boardState = data.tahta;
                whiteTurn = data.beyaz_sirasi;
                isCheck = data.sah_tehdit;
                
                document.getElementById('w-score').innerText = data.b_skor;
                document.getElementById('w-caps').innerText = data.y_siyah.join(' ');
                document.getElementById('b-score').innerText = data.s_skor;
                document.getElementById('b-caps').innerText = data.y_beyaz.join(' ');
                
                const wClock = document.getElementById('w-clock');
                const bClock = document.getElementById('b-clock');
                wClock.innerText = formatTime(data.beyaz_sure);
                bClock.innerText = formatTime(data.siyah_sure);
                wClock.classList.toggle('danger', data.beyaz_sure <= 30 && whiteTurn);
                bClock.classList.toggle('danger', data.siyah_sure <= 30 && !whiteTurn);

                document.querySelectorAll('.time-btn').forEach(btn => {
                    btn.classList.toggle('active', btn.innerText.startsWith(data.secili_dakika + ''));
                });

                if (data.mesaj) document.getElementById('msg').innerText = data.mesaj;

                document.getElementById('card-white').classList.toggle('active-turn', whiteTurn);
                document.getElementById('card-black').classList.toggle('active-turn', !whiteTurn);

                render();
            } catch(e) {}
        }

        function render() {
            const bEl = document.getElementById('board');
            bEl.innerHTML = '';
            const isFlipped = (mySide === 'siyah');

            for (let i = 0; i < 8; i++) {
                for (let j = 0; j < 8; j++) {
                    const r = isFlipped ? (7 - i) : i;
                    const c = isFlipped ? (7 - j) : j;

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
                        const dot = document.createElement('div');
                        dot.className = 'valid-dot';
                        sq.appendChild(dot);
                    }

                    sq.onmousedown = (e) => { e.preventDefault(); onSquareClick(r, c); };
                    bEl.appendChild(sq);
                }
            }
        }

        async function onSquareClick(r, c) {
            const isMyTurn = (mySide === 'beyaz' && whiteTurn) || (mySide === 'siyah' && !whiteTurn);
            if (!isMyTurn || isProcessing) return;

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

            if ((whiteTurn && isWhitePiece && mySide === 'beyaz') || (!whiteTurn && isBlackPiece && mySide === 'siyah')) {
                selected = [r, c];
                isProcessing = true;
                const res = await fetch('/api/valid_moves?oda=' + currentRoom, {
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
            const res = await fetch('/api/move?oda=' + currentRoom, {
                method: 'POST', headers: {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token},
                body: JSON.stringify({ from: from, to: to, promotion: promo })
            });
            const data = await res.json();
            if (data.success) {
                selected = null; validMoves = [];
                await fetchState();
            } else {
                document.getElementById('msg').innerText = data.error;
            }
            isProcessing = false;
        }

        async function undoGame() {
            if (isProcessing) return;
            isProcessing = true;
            await fetch('/api/undo?oda=' + currentRoom, { method: 'POST', headers: {'Authorization': 'Bearer ' + token} });
            selected = null; validMoves = [];
            await fetchState();
            isProcessing = false;
        }
    </script>
</body>
</html>"""

# =====================================================================
# 5. API ROTLARI VE TOKEN DOĞRULAMA
# =====================================================================
def get_or_create_room(oda_id):
    if oda_id not in odalar:
        odalar[oda_id] = yeni_oda_olustur()
    return odalar[oda_id]

def token_dogrula(req):
    auth = req.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        t = auth.split(' ')[1]
        try:
            return jwt.decode(t, SECRET_KEY, algorithms=["HS256"])
        except:
            return None
    return None

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

@app.route('/api/set_time', methods=['POST'])
def api_set_time():
    if not token_dogrula(request): return jsonify({'error': 'Yetkisiz erişim'}), 401
    oda = get_or_create_room(request.args.get('oda', 'varsayilan'))
    mins = int(request.json.get('minutes', 3))
    oda['secili_dakika'] = mins
    oda['beyaz_sure'] = mins * 60
    oda['siyah_sure'] = mins * 60
    oda['son_zaman'] = time.time()
    oda['oyun_basladi'] = False
    return jsonify({'success': True})

@app.route('/api/state')
def api_state():
    if not token_dogrula(request): return jsonify({'error': 'Yetkisiz erişim'}), 401
    oda = get_or_create_room(request.args.get('oda', 'varsayilan'))
    sure_guncelle(oda)
    k_sat, k_sut = sah_konumu_bul(oda['tahta'], oda['beyaz_sirasi'])
    sah_tehdidi = tehdit_altinda_mi(oda['tahta'], k_sat, k_sut, not oda['beyaz_sirasi']) if k_sat != -1 else False
    return jsonify({
        'tahta': oda['tahta'], 'beyaz_sirasi': oda['beyaz_sirasi'], 'sah_tehdit': sah_tehdidi,
        'b_skor': oda['b_skor'], 's_skor': oda['s_skor'],
        'y_beyaz': oda['y_beyaz'], 'y_siyah': oda['y_siyah'], 'mesaj': oda['mesaj'],
        'secili_dakika': oda['secili_dakika'],
        'beyaz_sure': round(oda['beyaz_sure']),
        'siyah_sure': round(oda['siyah_sure'])
    })

@app.route('/api/valid_moves', methods=['POST'])
def api_valid():
    if not token_dogrula(request): return jsonify({'error': 'Yetkisiz erişim'}), 401
    oda = get_or_create_room(request.args.get('oda', 'varsayilan'))
    req = request.json or {}
    return jsonify({'moves': gecerli_hamleleri_bul(oda, req.get('r'), req.get('c'), oda['beyaz_sirasi'])})

@app.route('/api/move', methods=['POST'])
def api_move():
    if not token_dogrula(request): return jsonify({'error': 'Yetkisiz erişim'}), 401
    oda = get_or_create_room(request.args.get('oda', 'varsayilan'))
    data = request.json or {}
    b_sat, b_sut = data.get('from')
    h_sat, h_sut = data.get('to')
    terfi = data.get('promotion')
    
    tahta = oda['tahta']
    secilen = tahta[b_sat][b_sut]
    hedef = tahta[h_sat][h_sut]
    gecerliler = gecerli_hamleleri_bul(oda, b_sat, b_sut, oda['beyaz_sirasi'])

    if [h_sat, h_sut] not in gecerliler:
        return jsonify({'success': False, 'error': 'Kural dışı hamle!'})

    oda['oyun_basladi'] = True
    oda['son_zaman'] = time.time()

    # Zaman Makinesi (Undo)
    oda['hamle_gecmisi'].append({
        'tahta': [s[:] for s in tahta], 'sira': oda['beyaz_sirasi'],
        'b_skor': oda['b_skor'], 's_skor': oda['s_skor'],
        'y_beyaz': list(oda['y_beyaz']), 'y_siyah': list(oda['y_siyah']),
        'b_sah': oda['b_sah'], 'b_k_sol': oda['b_k_sol'], 'b_k_sag': oda['b_k_sag'],
        's_sah': oda['s_sah'], 's_k_sol': oda['s_k_sol'], 's_k_sag': oda['s_k_sag'],
        'gecerken': oda['gecerken'], 'elli_sayac': oda['elli_sayac'],
        'b_sure': oda['beyaz_sure'], 's_sure': oda['siyah_sure']
    })

    tas_yendi = False
    yeni_ep = None
    if secilen.upper() == 'P':
        yon = -1 if oda['beyaz_sirasi'] else 1
        if abs(h_sat - b_sat) == 2: yeni_ep = (b_sat + yon, b_sut)
        if abs(h_sut - b_sut) == 1 and hedef == ' ' and oda['gecerken'] == (h_sat, h_sut):
            alinan = tahta[h_sat - yon][h_sut]
            tahta[h_sat - yon][h_sut] = ' '
            tas_yendi = True
            if oda['beyaz_sirasi']:
                oda['b_skor'] += 1; oda['y_siyah'].append(SEMBOLLER[alinan])
            else:
                oda['s_skor'] += 1; oda['y_beyaz'].append(SEMBOLLER[alinan])

    oda['gecerken'] = yeni_ep

    if hedef != ' ':
        tas_yendi = True
        puan = TAS_PUANLARI.get(hedef.upper(), 0)
        if oda['beyaz_sirasi']:
            oda['b_skor'] += puan; oda['y_siyah'].append(SEMBOLLER[hedef])
        else:
            oda['s_skor'] += puan; oda['y_beyaz'].append(SEMBOLLER[hedef])

    # 50 Hamle Kural Sayacı
    oda['elli_sayac'] = 0 if (secilen.upper() == 'P' or tas_yendi) else oda['elli_sayac'] + 1

    # Rok Kale Hareketi
    if secilen.upper() == 'K' and abs(h_sut - b_sut) == 2:
        if h_sut == 6: tahta[h_sat][5] = tahta[h_sat][7]; tahta[h_sat][7] = ' '
        elif h_sut == 2: tahta[h_sat][3] = tahta[h_sat][0]; tahta[h_sat][0] = ' '

    # Terfi
    if secilen.upper() == 'P' and terfi:
        tahta[h_sat][h_sut] = terfi.upper() if oda['beyaz_sirasi'] else terfi.lower()
    else:
        tahta[h_sat][h_sut] = secilen
    tahta[b_sat][b_sut] = ' '

    # Bayraklar
    if secilen == 'K': oda['b_sah'] = True
    elif secilen == 'k': oda['s_sah'] = True
    elif secilen == 'R':
        if (b_sat, b_sut) == (7, 0): oda['b_k_sol'] = True
        elif (b_sat, b_sut) == (7, 7): oda['b_k_sag'] = True
    elif secilen == 'r':
        if (b_sat, b_sut) == (0, 0): oda['s_k_sol'] = True
        elif (b_sat, b_sut) == (0, 7): oda['s_k_sag'] = True

    oda['beyaz_sirasi'] = not oda['beyaz_sirasi']

    # 3 Kez Konum Tekrarı Takibi
    durum_anahtari = tahta_durum_anahtari(oda)
    oda['konum_gecmisi'][durum_anahtari] = oda['konum_gecmisi'].get(durum_anahtari, 0) + 1

    # Tüm Beraberlik ve Mat Durumları
    s_r, s_c = sah_konumu_bul(tahta, oda['beyaz_sirasi'])
    tehdit = tehdit_altinda_mi(tahta, s_r, s_c, not oda['beyaz_sirasi']) if s_r != -1 else False
    kalan_hamle = tum_gecerli_hamleler_sayisi(oda, oda['beyaz_sirasi'])

    if kalan_hamle == 0:
        if tehdit:
            kazanan = 'Beyaz' if not oda['beyaz_sirasi'] else 'Siyah'
            oda['mesaj'] = f"ŞAH MAT! {kazanan} Kazandı!"
            mac_kaydet("vahit", oda['b_skor'], oda['s_skor'], kazanan)
        else:
            oda['mesaj'] = "PAT! Oyun Berabere."
            mac_kaydet("vahit", oda['b_skor'], oda['s_skor'], "BERABERE")
    elif oda['elli_sayac'] >= 100:
        oda['mesaj'] = "50 Hamle Kuralı Nedeniyle Berabere!"
        mac_kaydet("vahit", oda['b_skor'], oda['s_skor'], "BERABERE")
    elif oda['konum_gecmisi'].get(durum_anahtari, 0) >= 3:
        oda['mesaj'] = "3 Kez Konum Tekrarı Nedeniyle Berabere!"
        mac_kaydet("vahit", oda['b_skor'], oda['s_skor'], "BERABERE")
    elif yetersiz_materyal_mi(tahta):
        oda['mesaj'] = "Yetersiz Materyal Nedeniyle Berabere!"
        mac_kaydet("vahit", oda['b_skor'], oda['s_skor'], "BERABERE")

    return jsonify({'success': True})

@app.route('/api/undo', methods=['POST'])
def api_undo():
    if not token_dogrula(request): return jsonify({'error': 'Yetkisiz erişim'}), 401
    oda = get_or_create_room(request.args.get('oda', 'varsayilan'))
    if oda['hamle_gecmisi']:
        eski = oda['hamle_gecmisi'].pop()
        oda['tahta'] = eski['tahta']; oda['beyaz_sirasi'] = eski['sira']
        oda['b_skor'] = eski['b_skor']; oda['s_skor'] = eski['s_skor']
        oda['y_beyaz'] = list(eski['y_beyaz']); oda['y_siyah'] = list(eski['y_siyah'])
        oda['b_sah'] = eski['b_sah']; oda['b_k_sol'] = eski['b_k_sol']; oda['b_k_sag'] = eski['b_k_sag']
        oda['s_sah'] = eski['s_sah']; oda['s_k_sol'] = eski['s_k_sol']; oda['s_k_sag'] = eski['s_k_sag']
        oda['gecerken'] = eski['gecerken']; oda['elli_sayac'] = eski['elli_sayac']
        oda['beyaz_sure'] = eski.get('b_sure', oda['beyaz_sure'])
        oda['siyah_sure'] = eski.get('s_sure', oda['siyah_sure'])
        oda['mesaj'] = ''
    return jsonify({'success': True})

@app.route('/api/reset', methods=['POST'])
def api_reset():
    if not token_dogrula(request): return jsonify({'error': 'Yetkisiz erişim'}), 401
    oda_id = request.args.get('oda', 'varsayilan')
    if oda_id in odalar:
        odalar[oda_id] = yeni_oda_olustur(odalar[oda_id]['secili_dakika'])
    return jsonify({'success': True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
