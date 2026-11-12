import os
import time
import sqlite3
import threading
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
        'beyaz_ad': '',
        'siyah_ad': ''
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
# 4. HTML ARAYÜZ
# =====================================================================
HTML_PAGE = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="google-site-verification" content="lIdhFOFea-Gne9dwQpDCUbceGuTWtpOVv-SRFOeaw-o" />
    <title>Goaltech Chess Online</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;700;800&family=JetBrains+Mono:wght@600;700&display=swap" rel="stylesheet">
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

        #welcome-screen { position: fixed; inset: 0; display: flex; align-items: center; justify-content: center; z-index: 100; backdrop-filter: blur(6px); }
        .welcome-box { background: var(--card-bg); border: 1px solid var(--card-border); padding: 36px; border-radius: 24px; text-align: center; width: 340px; max-width: calc(100vw - 32px); box-shadow: 0 20px 50px rgba(0,0,0,0.5); animation: popIn 0.6s cubic-bezier(.2,1.3,.4,1) both; backdrop-filter: blur(16px); }
        .welcome-knight { font-size: 64px; display: inline-block; animation: knightHop 2.4s ease-in-out infinite; filter: drop-shadow(0 8px 16px rgba(139,92,246,0.6)); }
        @keyframes knightHop { 0%,100% { transform: translateY(0) rotate(0); } 30% { transform: translateY(-14px) rotate(-8deg); } 60% { transform: translateY(0) rotate(4deg); } }
        .welcome-box h1 { margin: 6px 0 18px; font-size: 32px; font-weight: 800; letter-spacing: -1px; background: linear-gradient(90deg, #c4b5fd, #67e8f9, #f0abfc, #c4b5fd); background-size: 300% 100%; -webkit-background-clip: text; background-clip: text; color: transparent; animation: shine 6s linear infinite; }
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
            .action-grid { gap: 8px !important; }
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

        .action-grid { width: 100%; display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 12px; }
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

    <div id="welcome-screen">
        <div class="welcome-box">
            <div class="welcome-knight">♞</div>
            <h1>GOALTECH</h1>
            <div class="input-group">
                <label for="username">Oyuncu Adı</label>
                <input type="text" id="username" value="Oyuncu_1" maxlength="20">
            </div>
            <button class="btn-main" onclick="joinGame()">Oyuna Başla</button>
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
                    <span class="title">Beyaz (<span class="score-num" id="w-score">0</span>)</span>
                    <span class="clock-display" id="w-clock">03:00</span>
                </div>
                <div class="caps" id="w-caps"></div>
            </div>
            <div class="score-card" id="card-black">
                <div class="card-header">
                    <span class="title">Siyah (<span class="score-num" id="b-score">0</span>)</span>
                    <span class="clock-display" id="b-clock">03:00</span>
                </div>
                <div class="caps" id="b-caps"></div>
            </div>
        </div>

        <div class="board-wrapper" id="board-container">
            <div class="waiting-overlay">
                <div class="wait-text">
                    Bağlantı Bekleniyor... ⏳
                    <span class="wait-sub">Arkadaşının odaya girmesi bekleniyor — "Paylaş" ile linki gönder</span>
                </div>
            </div>
            <div class="board" id="board"></div>
        </div>

        <div id="msg"></div>

        <div class="action-grid">
            <button class="btn-modern btn-share" onclick="nativeShare()">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>
                Paylaş
            </button>
            <button class="btn-modern btn-undo" onclick="undoGame()">↩ Geri Al</button>
            <button class="btn-modern btn-logout" onclick="leaveGame()">Ayrıl</button>
        </div>
    </div>

    <div id="promo-modal" class="modal">
        <div class="modal-content">
            <h3 style="margin:0; font-size:16px;">Terfi Edecek Taşı Seç</h3>
            <div class="promo-pieces" id="promo-options"></div>
        </div>
    </div>

    <div id="gameover-modal" class="modal">
        <div class="modal-content">
            <div class="gameover-icon" id="gameover-icon">🏆</div>
            <div class="gameover-title" id="gameover-title"></div>
            <div class="modal-actions">
                <button class="btn-main" onclick="rematch()">🔄 Yeni Oyun</button>
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

        function storeGet(store, key) { try { return store.getItem(key); } catch (e) { return null; } }
        function storeSet(store, key, val) { try { store.setItem(key, val); } catch (e) {} }
        function storeDel(store, key) { try { store.removeItem(key); } catch (e) {} }

        // Oda ve taraf: oda linkte tutulur, taraf sekmeye özel saklanır (sayfa yenilense de korunur)
        const urlParams = new URLSearchParams(window.location.search);
        let currentRoom = urlParams.get('oda');
        let mySide;
        if (!currentRoom) {
            currentRoom = 'oda_' + Math.random().toString(36).substring(2, 8);
            mySide = 'beyaz';
        } else {
            mySide = storeGet(sessionStorage, 'goaltech_side_' + currentRoom) || 'siyah';
        }
        storeSet(sessionStorage, 'goaltech_side_' + currentRoom, mySide);
        try { history.replaceState(null, '', window.location.pathname + '?oda=' + encodeURIComponent(currentRoom)); } catch (e) {}

        const roomQ = () => 'oda=' + encodeURIComponent(currentRoom);

        let playerName = storeGet(localStorage, 'goaltech_player');
        let boardState = [], selected = null, validMoves = [], whiteTurn = true, isCheck = false;
        let isProcessing = false;
        let pendingMove = null;
        let pollingTimer = null;
        let domSquares = [];
        let isBothConnected = false;
        let gameOver = false;
        let lastMove = null;
        let moveNo = null;
        let lastScores = null;
        let capCount = null;
        let reqSeq = 0, appliedSeq = 0;
        let fetchInFlight = false;
        let joining = false;
        let gameOverShownFor = null;

        spawnBackgroundPieces();
        if (playerName) {
            document.getElementById('username').value = playerName;
            joinRoomLogic().finally(showGame);
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

        async function joinGame() {
            const u = document.getElementById('username').value.trim().slice(0, 20) || 'Oyuncu';
            playerName = u;
            storeSet(localStorage, 'goaltech_player', playerName);
            await joinRoomLogic();
            showGame();
        }

        async function joinRoomLogic() {
            if (joining) return;
            joining = true;
            try {
                await fetch('/api/join?' + roomQ() + '&taraf=' + mySide + '&ad=' + encodeURIComponent(playerName || ''), { method: 'POST' });
            } catch (e) {
            } finally {
                joining = false;
            }
        }

        function showGame() {
            document.getElementById('welcome-screen').style.display = 'none';
            document.getElementById('game-screen').style.display = 'flex';
            document.getElementById('role-badge').innerText = playerName + ' (' + (mySide === 'beyaz' ? 'Beyaz ♔' : 'Siyah ♚') + ')';

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
                await fetch('/api/set_time?' + roomQ(), {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ minutes: mins })
                });
            } catch (e) {}
            await fetchState();
        }

        async function leaveGame() {
            clearInterval(pollingTimer);
            pollingTimer = null;
            try { await fetch('/api/reset?' + roomQ() + '&taraf=' + mySide, { method: 'POST' }); } catch (e) {}
            storeDel(localStorage, 'goaltech_player');
            storeDel(sessionStorage, 'goaltech_side_' + currentRoom);
            window.location.href = window.location.origin + window.location.pathname;
        }

        async function rematch() {
            closeGameOver();
            try { await fetch('/api/rematch?' + roomQ(), { method: 'POST' }); } catch (e) {}
            selected = null; validMoves = [];
            gameOverShownFor = null;
            await fetchState();
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

        async function fetchState() {
            if (fetchInFlight) return;
            fetchInFlight = true;
            const mySeq = ++reqSeq;
            try {
                const res = await fetch('/api/state?' + roomQ());
                const data = await res.json();
                if (mySeq < appliedSeq) return;   // eski cevap, yoksay
                appliedSeq = mySeq;
                applyState(data);
            } catch (e) {
            } finally {
                fetchInFlight = false;
            }
        }

        function applyState(data) {
            // Sunucu yeniden başlarsa oda kaybolur; bu durumda odaya tekrar katıl
            const meConnected = mySide === 'beyaz' ? data.beyaz_baglandi : data.siyah_baglandi;
            if (!meConnected && playerName) joinRoomLogic();

            const prevMoveNo = moveNo;
            boardState = data.tahta;
            whiteTurn = data.beyaz_sirasi;
            isCheck = data.sah_tehdit;
            gameOver = data.oyun_bitti;
            lastMove = data.son_hamle;
            moveNo = data.hamle_no;
            isBothConnected = data.siyah_baglandi && data.beyaz_baglandi;

            if (prevMoveNo !== null && prevMoveNo !== moveNo) { selected = null; validMoves = []; }

            document.getElementById('board-container').classList.toggle('waiting', !isBothConnected);
            document.getElementById('time-bar').classList.toggle('locked', moveNo > 0 && !gameOver);

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
        }

        function updateMessage(serverMsg) {
            const msg = document.getElementById('msg');
            if (serverMsg) {
                msg.innerText = serverMsg;
                msg.className = '';
                return;
            }
            if (!isBothConnected) { msg.innerText = ''; msg.className = ''; return; }
            const myTurn = (mySide === 'beyaz') === whiteTurn;
            if (isCheck && myTurn) { msg.innerText = 'ŞAH! Şahını korumalısın ⚠️'; msg.className = ''; return; }
            msg.innerText = myTurn ? 'Sıra sende ✨' : 'Rakip düşünüyor... 🤔';
            msg.className = myTurn ? 'my-turn' : 'info';
        }

        function bumpEl(el) {
            el.classList.remove('bump');
            void el.offsetWidth;
            el.classList.add('bump');
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
                icon.innerText = iWon ? '🏆' : '😔';
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
            if (!isBothConnected || gameOver) return;

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
                    const res = await fetch('/api/valid_moves?' + roomQ(), {
                        method: 'POST', headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ r, c, taraf: mySide })
                    });
                    const data = await res.json();
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
            const modal = document.getElementById('promo-modal');
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
            modal.classList.add('open');
        }

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
                const res = await fetch('/api/move?' + roomQ(), {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ from: from, to: to, promotion: promo, taraf: mySide })
                });
                const data = await res.json();
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
            fetchInFlight = false;   // hamleden sonraki durumu hemen çek
            await fetchState();
        }

        async function undoGame() {
            if (isProcessing || !isBothConnected) return;
            if (!moveNo) { showToast('Geri alınacak hamle yok'); return; }
            isProcessing = true;
            try {
                await fetch('/api/undo?' + roomQ(), { method: 'POST' });
            } catch (e) {
            } finally {
                selected = null; validMoves = [];
                isProcessing = false;
            }
            fetchInFlight = false;
            await fetchState();
        }
    </script>
</body>
</html>"""

# =====================================================================
# 5. API ROTLARI
# =====================================================================
def odalari_temizle():
    simdi = time.time()
    for oda_id in [k for k, v in odalar.items() if simdi - v['son_erisim'] > ODA_ZAMAN_ASIMI]:
        del odalar[oda_id]

def oda_id_al():
    return (request.args.get('oda') or 'varsayilan')[:64]

def get_or_create_room(oda_id):
    if oda_id not in odalar:
        odalari_temizle()
        odalar[oda_id] = yeni_oda_olustur()
    oda = odalar[oda_id]
    oda['son_erisim'] = time.time()
    return oda

def kare_al(deger):
    try:
        r, c = int(deger[0]), int(deger[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    if 0 <= r < 8 and 0 <= c < 8:
        return r, c
    return None

def taraf_dogru_mu(oda, taraf):
    # taraf gönderilmemişse eski istemcilerle uyumluluk için izin ver
    if taraf not in ('beyaz', 'siyah'):
        return True
    return (taraf == 'beyaz') == oda['beyaz_sirasi']

@app.route('/')
def home():
    return HTML_PAGE

@app.route('/api/join', methods=['POST'])
def api_join():
    with kilit:
        oda = get_or_create_room(oda_id_al())
        taraf = request.args.get('taraf', 'beyaz')
        ad = (request.args.get('ad') or '').strip()[:20]
        if taraf == 'beyaz':
            oda['beyaz_baglandi'] = True
            if ad: oda['beyaz_ad'] = ad
        elif taraf == 'siyah':
            oda['siyah_baglandi'] = True
            if ad: oda['siyah_ad'] = ad
        return jsonify({'success': True})

@app.route('/api/set_time', methods=['POST'])
def api_set_time():
    with kilit:
        oda = get_or_create_room(oda_id_al())
        data = request.get_json(silent=True) or {}
        try:
            mins = int(data.get('minutes', 3))
        except (TypeError, ValueError):
            return jsonify({'success': False, 'error': 'Geçersiz süre'})
        if mins not in IZINLI_DAKIKALAR:
            return jsonify({'success': False, 'error': 'Geçersiz süre'})
        if oda['hamle_gecmisi'] and not oda['oyun_bitti']:
            return jsonify({'success': False, 'error': 'Oyun başladıktan sonra süre değiştirilemez'})
        if oda['oyun_bitti']:
            # Bitmiş oyunda süre seçilirse yeni oyun başlat
            eski = oda
            oda = yeni_oda_olustur(mins)
            for k in ('beyaz_baglandi', 'siyah_baglandi', 'beyaz_ad', 'siyah_ad'):
                oda[k] = eski[k]
            odalar[oda_id_al()] = oda
        oda['secili_dakika'] = mins
        oda['beyaz_sure'] = mins * 60
        oda['siyah_sure'] = mins * 60
        oda['son_zaman'] = time.time()
        oda['oyun_basladi'] = False
        return jsonify({'success': True})

@app.route('/api/state')
def api_state():
    with kilit:
        oda = get_or_create_room(oda_id_al())
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
            'beyaz_baglandi': oda['beyaz_baglandi'],
            'siyah_baglandi': oda['siyah_baglandi'],
            'oyun_bitti': oda['oyun_bitti'],
            'sonuc_tipi': oda['sonuc_tipi'],
            'son_hamle': oda['son_hamle'],
            'hamle_no': len(oda['hamle_gecmisi'])
        })

@app.route('/api/valid_moves', methods=['POST'])
def api_valid():
    with kilit:
        oda = get_or_create_room(oda_id_al())
        req = request.get_json(silent=True) or {}
        kare = kare_al([req.get('r'), req.get('c')])
        if kare is None or oda['oyun_bitti'] or not taraf_dogru_mu(oda, req.get('taraf')):
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
        b_sat, b_sut = bas
        h_sat, h_sut = hed
        terfi = data.get('promotion')

        # Önce süreyi düş: süre bittiyse hamle kabul edilmez
        sure_guncelle(oda)
        if oda['oyun_bitti']:
            return jsonify({'success': False, 'error': 'Oyun bitti!'})
        if not (oda['beyaz_baglandi'] and oda['siyah_baglandi']):
            return jsonify({'success': False, 'error': 'Rakip henüz bağlanmadı!'})
        if not taraf_dogru_mu(oda, data.get('taraf')):
            return jsonify({'success': False, 'error': 'Sıra sende değil!'})

        tahta = oda['tahta']
        secilen = tahta[b_sat][b_sut]
        hedef = tahta[h_sat][h_sut]
        gecerliler = gecerli_hamleleri_bul(oda, b_sat, b_sut, oda['beyaz_sirasi'])

        if [h_sat, h_sut] not in gecerliler:
            return jsonify({'success': False, 'error': 'Kural dışı hamle!'})

        oda['hamle_gecmisi'].append({
            'tahta': [s[:] for s in tahta], 'sira': oda['beyaz_sirasi'],
            'b_skor': oda['b_skor'], 's_skor': oda['s_skor'],
            'y_beyaz': list(oda['y_beyaz']), 'y_siyah': list(oda['y_siyah']),
            'b_sah': oda['b_sah'], 'b_k_sol': oda['b_k_sol'], 'b_k_sag': oda['b_k_sag'],
            's_sah': oda['s_sah'], 's_k_sol': oda['s_k_sol'], 's_k_sag': oda['s_k_sag'],
            'gecerken': oda['gecerken'], 'elli_sayac': oda['elli_sayac'],
            'b_sure': oda['beyaz_sure'], 's_sure': oda['siyah_sure'],
            'konum_gecmisi': dict(oda['konum_gecmisi']),
            'son_hamle': oda['son_hamle'], 'oyun_basladi': oda['oyun_basladi']
        })

        oda['oyun_basladi'] = True
        oda['son_zaman'] = time.time()
        oda['mesaj'] = ''
        son_hamle = [[[b_sat, b_sut], [h_sat, h_sut]]]

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
            # Köşedeki kale yenirse o tarafın rok hakkı da gider
            if hedef == 'R':
                if (h_sat, h_sut) == (7, 0): oda['b_k_sol'] = True
                elif (h_sat, h_sut) == (7, 7): oda['b_k_sag'] = True
            elif hedef == 'r':
                if (h_sat, h_sut) == (0, 0): oda['s_k_sol'] = True
                elif (h_sat, h_sut) == (0, 7): oda['s_k_sag'] = True

        oda['elli_sayac'] = 0 if (secilen.upper() == 'P' or tas_yendi) else oda['elli_sayac'] + 1

        if secilen.upper() == 'K' and abs(h_sut - b_sut) == 2:
            if h_sut == 6:
                tahta[h_sat][5] = tahta[h_sat][7]; tahta[h_sat][7] = ' '
                son_hamle.append([[h_sat, 7], [h_sat, 5]])
            elif h_sut == 2:
                tahta[h_sat][3] = tahta[h_sat][0]; tahta[h_sat][0] = ' '
                son_hamle.append([[h_sat, 0], [h_sat, 3]])

        if secilen.upper() == 'P' and h_sat in (0, 7):
            # Terfi seçilmemişse ya da geçersizse varsayılan olarak Vezir
            secim = str(terfi).upper() if terfi else 'Q'
            if secim not in ('Q', 'R', 'B', 'N'):
                secim = 'Q'
            tahta[h_sat][h_sut] = secim if oda['beyaz_sirasi'] else secim.lower()
        else:
            tahta[h_sat][h_sut] = secilen
        tahta[b_sat][b_sut] = ' '

        if secilen == 'K': oda['b_sah'] = True
        elif secilen == 'k': oda['s_sah'] = True
        elif secilen == 'R':
            if (b_sat, b_sut) == (7, 0): oda['b_k_sol'] = True
            elif (b_sat, b_sut) == (7, 7): oda['b_k_sag'] = True
        elif secilen == 'r':
            if (b_sat, b_sut) == (0, 0): oda['s_k_sol'] = True
            elif (b_sat, b_sut) == (0, 7): oda['s_k_sag'] = True

        oda['son_hamle'] = son_hamle
        oda['beyaz_sirasi'] = not oda['beyaz_sirasi']

        durum_anahtari = tahta_durum_anahtari(oda)
        oda['konum_gecmisi'][durum_anahtari] = oda['konum_gecmisi'].get(durum_anahtari, 0) + 1

        s_r, s_c = sah_konumu_bul(tahta, oda['beyaz_sirasi'])
        tehdit = tehdit_altinda_mi(tahta, s_r, s_c, not oda['beyaz_sirasi']) if s_r != -1 else False
        kalan_hamle = tum_gecerli_hamleler_sayisi(oda, oda['beyaz_sirasi'])

        if kalan_hamle == 0:
            if tehdit:
                kazanan = 'Beyaz' if not oda['beyaz_sirasi'] else 'Siyah'
                oyunu_bitir(oda, f"ŞAH MAT! {kazanan} Kazandı!", kazanan, 'mat')
            else:
                oyunu_bitir(oda, "PAT! Oyun Berabere.", "BERABERE", 'berabere')
        elif oda['elli_sayac'] >= 100:
            oyunu_bitir(oda, "50 Hamle Kuralı Nedeniyle Berabere!", "BERABERE", 'berabere')
        elif oda['konum_gecmisi'].get(durum_anahtari, 0) >= 3:
            oyunu_bitir(oda, "3 Kez Konum Tekrarı Nedeniyle Berabere!", "BERABERE", 'berabere')
        elif yetersiz_materyal_mi(tahta):
            oyunu_bitir(oda, "Yetersiz Materyal Nedeniyle Berabere!", "BERABERE", 'berabere')

        return jsonify({'success': True})

@app.route('/api/undo', methods=['POST'])
def api_undo():
    with kilit:
        oda = get_or_create_room(oda_id_al())
        if oda['hamle_gecmisi']:
            eski = oda['hamle_gecmisi'].pop()
            oda['tahta'] = eski['tahta']; oda['beyaz_sirasi'] = eski['sira']
            oda['b_skor'] = eski['b_skor']; oda['s_skor'] = eski['s_skor']
            oda['y_beyaz'] = list(eski['y_beyaz']); oda['y_siyah'] = list(eski['y_siyah'])
            oda['b_sah'] = eski['b_sah']; oda['b_k_sol'] = eski['b_k_sol']; oda['b_k_sag'] = eski['b_k_sag']
            oda['s_sah'] = eski['s_sah']; oda['s_k_sol'] = eski['s_k_sol']; oda['s_k_sag'] = eski['s_k_sag']
            oda['gecerken'] = eski['gecerken']; oda['elli_sayac'] = eski['elli_sayac']
            oda['beyaz_sure'] = eski['b_sure']
            oda['siyah_sure'] = eski['s_sure']
            oda['konum_gecmisi'] = dict(eski['konum_gecmisi'])
            oda['son_hamle'] = eski['son_hamle']
            oda['oyun_basladi'] = eski['oyun_basladi']
            oda['son_zaman'] = time.time()
            oda['oyun_bitti'] = False
            oda['sonuc_tipi'] = ''
            oda['mesaj'] = ''
        return jsonify({'success': True})

@app.route('/api/rematch', methods=['POST'])
def api_rematch():
    with kilit:
        oda_id = oda_id_al()
        eski = get_or_create_room(oda_id)
        yeni = yeni_oda_olustur(eski['secili_dakika'])
        for k in ('beyaz_baglandi', 'siyah_baglandi', 'beyaz_ad', 'siyah_ad'):
            yeni[k] = eski[k]
        odalar[oda_id] = yeni
        return jsonify({'success': True})

@app.route('/api/reset', methods=['POST'])
def api_reset():
    with kilit:
        oda_id = oda_id_al()
        taraf = request.args.get('taraf')
        if oda_id in odalar:
            eski = odalar[oda_id]
            yeni = yeni_oda_olustur(eski['secili_dakika'])
            # Ayrılan oyuncu bağlantısız sayılır, kalan oyuncunun bağlantısı korunur
            for t in ('beyaz', 'siyah'):
                if t != taraf:
                    yeni[f'{t}_baglandi'] = eski[f'{t}_baglandi']
                    yeni[f'{t}_ad'] = eski[f'{t}_ad']
            odalar[oda_id] = yeni
        return jsonify({'success': True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
