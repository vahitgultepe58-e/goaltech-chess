import os
import json
import time
import sqlite3
import jwt
from flask import Flask, render_template_string, jsonify, request

app = Flask(__name__)

# =====================================================================
# 1. VERİLER VE OYUN DURUMU
# =====================================================================
SEMBOLLER = {
    'K': '♔', 'Q': '♕', 'R': '♖', 'B': '♗', 'N': '♘', 'P': '♙',
    'k': '♚', 'q': '♛', 'r': '♜', 'b': '♝', 'n': '♞', 'p': '♟',
    ' ': ' '
}
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
            tاريخ DATETIME DEFAULT CURRENT_TIMESTAMP
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
        imlec.execute("INSERT INTO Mac_Gecmisi (oyuncu, beyaz_puan, siyah_puan, kazanan) VALUES (?, ?, ?, ?)", 
                      (s_oyuncu, s_beyaz, s_siyah, s_kazanan))
        baglanti.commit()
        baglanti.close()
    except Exception as e:
        print("VERİTABANI HATASI:", e)

veritabanini_kur()

# =====================================================================
# 3. KURAL MOTORU (SENİN ORİJİNAL FONKSİYONLARIN)
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

def kural_kontrol_ham(tas, b_sat, b_sut, h_sat, h_sut):
    tip = tas.upper()
    df_sat = abs(h_sat - b_sat)
    df_sut = abs(h_sut - b_sut)
    hedef = tahta[h_sat][h_sut]

    if tip == 'P':
        yon = -1 if tas.isupper() else 1
        baslangic = 6 if tas.isupper() else 1
        if b_sut == h_sut and hedef == ' ':
            if h_sat - b_sat == yon: return True
            if b_sat == baslangic and h_sat - b_sat == 2 * yon and tahta[b_sat + yon][b_sut] == ' ': return True
        if df_sut == 1 and h_sat - b_sat == yon and hedef != ' ': return True
        if df_sut == 1 and h_sat - b_sat == yon and hedef == ' ' and gecerken_alinabilir_kare == (h_sat, h_sut): return True
        return False
    elif tip == 'R': return (b_sat == h_sat or b_sut == h_sut) and yol_acik_mi(b_sat, b_sut, h_sat, h_sut)
    elif tip == 'B': return (df_sat == df_sut) and yol_acik_mi(b_sat, b_sut, h_sat, h_sut)
    elif tip == 'Q': return (b_sat == h_sat or b_sut == h_sut or df_sat == df_sut) and yol_acik_mi(b_sat, b_sut, h_sat, h_sut)
    elif tip == 'N': return (df_sat == 2 and df_sut == 1) or (df_sat == 1 and df_sut == 2)
    elif tip == 'K': return df_sat <= 1 and df_sut <= 1
    return False

def tehdit_altinda_mi(satir, sutun, saldirgan_beyaz_mi):
    for r in range(8):
        for c in range(8):
            tas = tahta[r][c]
            if tas != ' ' and tas.isupper() == saldirgan_beyaz_mi:
                if tas.upper() == 'P':
                    yon = -1 if tas.isupper() else 1
                    if satir - r == yon and abs(sutun - c) == 1: return True
                else:
                    if kural_kontrol_ham(tas, r, c, satir, sutun): return True
    return False

def kural_kontrol(tas, b_sat, b_sut, h_sat, h_sut):
    tip = tas.upper()
    if kural_kontrol_ham(tas, b_sat, b_sut, h_sat, h_sut): return True
    # ROK
    if tip == 'K' and b_sat == h_sat and abs(h_sut - b_sut) == 2:
        beyaz_mi = tas.isupper()
        if beyaz_mi and (b_sat, b_sut) == (7, 4):
            if beyaz_sah_oynadi or tehdit_altinda_mi(7, 4, False): return False
            if h_sut == 6:
                if beyaz_kale_sag_oynadi or tahta[7][7] != 'R' or tahta[7][5] != ' ' or tahta[7][6] != ' ': return False
                if tehdit_altinda_mi(7, 5, False) or tehdit_altinda_mi(7, 6, False): return False
                return True
            elif h_sut == 2:
                if beyaz_kale_sol_oynadi or tahta[7][0] != 'R' or tahta[7][1] != ' ' or tahta[7][2] != ' ' or tahta[7][3] != ' ': return False
                if tehdit_altinda_mi(7, 3, False) or tehdit_altinda_mi(7, 2, False): return False
                return True
        elif not beyaz_mi and (b_sat, b_sut) == (0, 4):
            if siyah_sah_oynadi or tehdit_altinda_mi(0, 4, True): return False
            if h_sut == 6:
                if siyah_kale_sag_oynadi or tahta[0][7] != 'r' or tahta[0][5] != ' ' or tahta[0][6] != ' ': return False
                if tehdit_altinda_mi(0, 5, True) or tehdit_altinda_mi(0, 6, True): return False
                return True
            elif h_sut == 2:
                if siyah_kale_sol_oynadi or tahta[0][0] != 'r' or tahta[0][1] != ' ' or tahta[0][2] != ' ' or tahta[0][3] != ' ': return False
                if tehdit_altinda_mi(0, 3, True) or tehdit_altinda_mi(0, 2, True): return False
                return True
    return False

def gecerli_hamleleri_bul(b_sat, b_sut, b_sirasi):
    secilen = tahta[b_sat][b_sut]
    hamleler = []
    for h_sat in range(8):
        for h_sut in range(8):
            hedef_tas = tahta[h_sat][h_sut]
            if hedef_tas == ' ' or hedef_tas.isupper() != b_sirasi:
                if kural_kontrol(secilen, b_sat, b_sut, h_sat, h_sut):
                    gecici_hedef = tahta[h_sat][h_sut]
                    alinan_en_passant_tas = ' '
                    en_passant_yapiliyor = False
                    if secilen.upper() == 'P' and abs(h_sut - b_sut) == 1 and gecici_hedef == ' ':
                        en_passant_yapiliyor = True
                        yon = -1 if b_sirasi else 1
                        alinan_en_passant_tas = tahta[h_sat - yon][h_sut]
                        tahta[h_sat - yon][h_sut] = ' '
                    tahta[h_sat][h_sut] = secilen
                    tahta[b_sat][b_sut] = ' '
                    
                    roklu_mu = False
                    kale_eski, kale_yeni = None, None
                    if secilen.upper() == 'K' and abs(h_sut - b_sut) == 2:
                        roklu_mu = True
                        if h_sut == 6: kale_eski, kale_yeni = (h_sat, 7), (h_sat, 5)
                        elif h_sut == 2: kale_eski, kale_yeni = (h_sat, 0), (h_sat, 3)
                        tahta[kale_yeni[0]][kale_yeni[1]] = tahta[kale_eski[0]][kale_eski[1]]
                        tahta[kale_eski[0]][kale_eski[1]] = ' '

                    sah_sat, sah_sut = sah_konumu_bul(b_sirasi)
                    if not tehdit_altinda_mi(sah_sat, sah_sut, not b_sirasi):
                        hamleler.append([h_sat, h_sut]) # JSON listesi olarak döner
                        
                    if roklu_mu:
                        tahta[kale_eski[0]][kale_eski[1]] = tahta[kale_yeni[0]][kale_yeni[1]]
                        tahta[kale_yeni[0]][kale_yeni[1]] = ' '
                    if en_passant_yapiliyor:
                        yon = -1 if b_sirasi else 1
                        tahta[h_sat - yon][h_sut] = alinan_en_passant_tas
                    tahta[b_sat][b_sut] = secilen
                    tahta[h_sat][h_sut] = gecici_hedef
    return hamleler

def tum_gecerli_hamlelerin_sayisi(b_sirasi):
    toplam = 0
    for r in range(8):
        for c in range(8):
            tas = tahta[r][c]
            if tas != ' ' and tas.isupper() == b_sirasi:
                toplam += len(gecerli_hamleleri_bul(r, c, b_sirasi))
    return toplam

def tahta_durum_anahtari(b_sirasi):
    t_str = "".join("".join(s) for s in tahta)
    r_str = f"{beyaz_sah_oynadi}{beyaz_kale_sol_oynadi}{beyaz_kale_sag_oynadi}{siyah_sah_oynadi}{siyah_kale_sol_oynadi}{siyah_kale_sag_oynadi}"
    return f"{t_str}_{b_sirasi}_{r_str}_{gecerken_alinabilir_kare}"

def oyunu_sifirla():
    global tahta, beyaz_skor, siyah_skor, beyaz_sirasi, hamle_gecmisi, konum_gecmisi
    global beyaz_sah_oynadi, beyaz_kale_sol_oynadi, beyaz_kale_sag_oynadi
    global siyah_sah_oynadi, siyah_kale_sol_oynadi, siyah_kale_sag_oynadi
    global gecerken_alinabilir_kare, elli_hamle_sayaci, yenilen_beyazlar, yenilen_siyahlar

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
    yenilen_beyazlar.clear(); yenilen_siyahlar.clear()
    hamle_gecmisi.clear(); konum_gecmisi.clear()
    beyaz_sirasi = True
    beyaz_sah_oynadi = beyaz_kale_sol_oynadi = beyaz_kale_sag_oynadi = False
    siyah_sah_oynadi = siyah_kale_sol_oynadi = siyah_kale_sag_oynadi = False
    gecerken_alinabilir_kare = None
    elli_hamle_sayaci = 0

# =====================================================================
# 4. FLASK WEB ARAYÜZÜ (HTML/JS)
# =====================================================================
HTML_PAGE = """<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Goaltech Chess</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, sans-serif; background: #12161c; color: #fff; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 10px; }
        h1 { margin: 0 0 10px 0; color: #4ade80; }
        .panels { display: flex; gap: 20px; margin-bottom: 10px; width: 100%; max-width: 520px; justify-content: space-between; }
        .score-box { background: #1e242d; padding: 10px; border-radius: 8px; flex: 1; border: 1px solid #333; }
        .score-box h3 { margin: 0 0 5px 0; font-size: 16px; color: #facc15; }
        .caps { font-size: 20px; color: #888; }
        .board { display: grid; grid-template-columns: repeat(8, 60px); grid-template-rows: repeat(8, 60px); border: 4px solid #27303f; border-radius: 8px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }
        @media (max-width: 520px) { .board { grid-template-columns: repeat(8, 42px); grid-template-rows: repeat(8, 42px); } .square { font-size: 28px !important; } }
        .square { display: flex; align-items: center; justify-content: center; font-size: 42px; cursor: pointer; user-select: none; position: relative; }
        .light { background-color: #ebecd0; color: #111; }
        .dark { background-color: #414b56; color: #111; }
        .selected { background-color: #facc15 !important; }
        .in-check { background-color: #ef4444 !important; }
        .valid-dot { width: 18px; height: 18px; background-color: #22c55e; border-radius: 50%; position: absolute; box-shadow: 0 0 5px rgba(0,0,0,0.5); }
        .controls { margin-top: 15px; display: flex; gap: 10px; }
        button { padding: 10px 16px; font-weight: bold; border: none; border-radius: 6px; cursor: pointer; background: #2563eb; color: white; transition: 0.2s; }
        button:hover { background: #1d4ed8; }
        .btn-undo { background: #059669; }
        .btn-undo:hover { background: #047857; }
        #msg { margin-top: 10px; font-weight: bold; color: #f87171; font-size: 18px; }
    </style>
</head>
<body>
    <h1>Goaltech Chess</h1>
    
    <div class="panels">
        <div class="score-box">
            <h3>Beyaz (<span id="w-score">0</span>)</h3>
            <div class="caps" id="w-caps"></div>
        </div>
        <div class="score-box">
            <h3>Siyah (<span id="b-score">0</span>)</h3>
            <div class="caps" id="b-caps"></div>
        </div>
    </div>

    <div class="board" id="board"></div>
    <div id="msg"></div>
    
    <div class="controls">
        <button class="btn-undo" onclick="undoGame()">↩ Hamleyi Geri Al</button>
        <button onclick="resetGame()">Yeni Oyun</button>
    </div>

    <script>
        const SYMBOLS = {'K':'♔','Q':'♕','R':'♖','B':'♗','N':'♘','P':'♙', 'k':'♚','q':'♛','r':'♜','b':'♝','n':'♞','p':'♟',' ':' '};
        let boardState = [], selected = null, validMoves = [], whiteTurn = true, isCheck = false;

        async function fetchState() {
            const res = await fetch('/api/state');
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
                    sq.innerText = SYMBOLS[piece] || '';
                    if (selected && selected[0] === r && selected[1] === c) sq.classList.add('selected');
                    if (isCheck && ((whiteTurn && piece === 'K') || (!whiteTurn && piece === 'k'))) sq.classList.add('in-check');
                    if (validMoves.some(m => m[0] === r && m[1] === c)) {
                        const dot = document.createElement('div'); dot.className = 'valid-dot'; sq.appendChild(dot);
                    }
                    sq.onclick = () => onSquareClick(r, c);
                    bEl.appendChild(sq);
                }
            }
        }

        async function onSquareClick(r, c) {
            document.getElementById('msg').innerText = '';
            const piece = boardState[r][c];
            
            if (selected && validMoves.some(m => m[0] === r && m[1] === c)) {
                let promo = null;
                const selPiece = boardState[selected[0]][selected[1]];
                if (selPiece.toUpperCase() === 'P' && (r === 0 || r === 7)) {
                    promo = prompt("Piyon terfisi! Q(Vezir), R(Kale), B(Fil), N(At)", "Q");
                    if (!['Q','R','B','N','q','r','b','n'].includes(promo)) promo = 'Q';
                }
                const res = await fetch('/api/move', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ from: selected, to: [r, c], promotion: promo })
                });
                const data = await res.json();
                if (data.success) {
                    selected = null; validMoves = [];
                    await fetchState();
                    if (data.mesaj) document.getElementById('msg').innerText = data.mesaj;
                } else {
                    document.getElementById('msg').innerText = data.error;
                }
                return;
            }

            const isWhitePiece = piece !== ' ' && piece === piece.toUpperCase();
            const isBlackPiece = piece !== ' ' && piece === piece.toLowerCase();
            
            if ((whiteTurn && isWhitePiece) || (!whiteTurn && isBlackPiece)) {
                selected = [r, c];
                const res = await fetch('/api/valid_moves', {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ r, c })
                });
                const data = await res.json();
                validMoves = data.moves || [];
                render();
            } else {
                selected = null; validMoves = []; render();
            }
        }

        async function undoGame() { await fetch('/api/undo', { method: 'POST' }); selected = null; validMoves = []; document.getElementById('msg').innerText = ''; fetchState(); }
        async function resetGame() { await fetch('/api/reset', { method: 'POST' }); selected = null; validMoves = []; document.getElementById('msg').innerText = ''; fetchState(); }
        fetchState();
    </script>
</body>
</html>"""

@app.route('/')
def home():
    return render_template_string(HTML_PAGE)

@app.route('/api/state')
def api_state():
    k_sat, k_sut = sah_konumu_bul(beyaz_sirasi)
    sah_tehdidi = tehdit_altinda_mi(k_sat, k_sut, not beyaz_sirasi) if k_sat != -1 else False
    return jsonify({
        'tahta': tahta, 'beyaz_sirasi': beyaz_sirasi, 'sah_tehdit': sah_tehdidi,
        'b_skor': beyaz_skor, 's_skor': siyah_skor,
        'y_beyaz': yenilen_beyazlar, 'y_siyah': yenilen_siyahlar
    })

@app.route('/api/valid_moves', methods=['POST'])
def api_valid():
    req = request.json or {}
    return jsonify({'moves': gecerli_hamleleri_bul(req.get('r'), req.get('c'), beyaz_sirasi)})

@app.route('/api/undo', methods=['POST'])
def api_undo():
    global tahta, beyaz_sirasi, beyaz_skor, siyah_skor, yenilen_beyazlar, yenilen_siyahlar
    global beyaz_sah_oynadi, beyaz_kale_sol_oynadi, beyaz_kale_sag_oynadi
    global siyah_sah_oynadi, siyah_kale_sol_oynadi, siyah_kale_sag_oynadi
    global gecerken_alinabilir_kare, elli_hamle_sayaci, hamle_gecmisi
    
    if hamle_gecmisi:
        eski = hamle_gecmisi.pop()
        tahta = eski['tahta']; beyaz_sirasi = eski['sira']
        beyaz_skor = eski['b_skor']; siyah_skor = eski['s_skor']
        yenilen_beyazlar = list(eski['y_beyaz']); yenilen_siyahlar = list(eski['y_siyah'])
        beyaz_sah_oynadi = eski['b_sah']; siyah_sah_oynadi = eski['s_sah']
        beyaz_kale_sol_oynadi = eski['b_k_sol']; beyaz_kale_sag_oynadi = eski['b_k_sag']
        siyah_kale_sol_oynadi = eski['s_k_sol']; siyah_kale_sag_oynadi = eski['s_k_sag']
        gecerken_alinabilir_kare = eski['gecerken']
        elli_hamle_sayaci = eski['elli_sayac']
    return jsonify({'success': True})

@app.route('/api/move', methods=['POST'])
def api_move():
    global tahta, beyaz_sirasi, beyaz_skor, siyah_skor, yenilen_beyazlar, yenilen_siyahlar
    global beyaz_sah_oynadi, beyaz_kale_sol_oynadi, beyaz_kale_sag_oynadi
    global siyah_sah_oynadi, siyah_kale_sol_oynadi, siyah_kale_sag_oynadi
    global gecerken_alinabilir_kare, elli_hamle_sayaci, konum_gecmisi, hamle_gecmisi

    data = request.json or {}
    b_sat, b_sut = data.get('from')
    h_sat, h_sut = data.get('to')
    terfi = data.get('promotion')
    
    secilen = tahta[b_sat][b_sut]
    hedef = tahta[h_sat][h_sut]
    gecerliler = gecerli_hamleleri_bul(b_sat, b_sut, beyaz_sirasi)
    
    if [h_sat, h_sut] not in gecerliler:
        return jsonify({'success': False, 'error': 'Kural dışı hamle!'})
        
    # 1. HAMLEYİ HAFIZAYA AL (UNDO İÇİN)
    hamle_gecmisi.append({
        'tahta': [s[:] for s in tahta], 'sira': beyaz_sirasi,
        'b_skor': beyaz_skor, 's_skor': siyah_skor,
        'y_beyaz': list(yenilen_beyazlar), 'y_siyah': list(yenilen_siyahlar),
        'b_sah': beyaz_sah_oynadi, 'b_k_sol': beyaz_kale_sol_oynadi, 'b_k_sag': beyaz_kale_sag_oynadi,
        's_sah': siyah_sah_oynadi, 's_k_sol': siyah_kale_sol_oynadi, 's_k_sag': siyah_kale_sag_oynadi,
        'gecerken': gecerken_alinabilir_kare, 'elli_sayac': elli_hamle_sayaci
    })

    tas_yendi_mi = False
    yeni_gecerken = None

    if secilen.upper() == 'P':
        yon = -1 if beyaz_sirasi else 1
        if abs(h_sat - b_sat) == 2:
            yeni_gecerken = (b_sat + yon, b_sut)
        if abs(h_sut - b_sut) == 1 and hedef == ' ' and gecerken_alinabilir_kare == (h_sat, h_sut):
            alinan_tas = tahta[h_sat - yon][h_sut]
            tahta[h_sat - yon][h_sut] = ' '
            tas_yendi_mi = True
            if beyaz_sirasi: beyaz_skor += TAS_PUANLARI['P']; yenilen_siyahlar.append(SEMBOLLER[alinan_tas])
            else: siyah_skor += TAS_PUANLARI['P']; yenilen_beyazlar.append(SEMBOLLER[alinan_tas])

    gecerken_alinabilir_kare = yeni_gecerken

    if hedef != ' ':
        tas_yendi_mi = True
        puan = TAS_PUANLARI.get(hedef.upper(), 0)
        if beyaz_sirasi: beyaz_skor += puan; yenilen_siyahlar.append(SEMBOLLER[hedef])
        else: siyah_skor += puan; yenilen_beyazlar.append(SEMBOLLER[hedef])

    elli_hamle_sayaci = 0 if (secilen.upper() == 'P' or tas_yendi_mi) else elli_hamle_sayaci + 1

    # ROK TAŞIMA İŞLEMİ
    if secilen.upper() == 'K' and abs(h_sut - b_sut) == 2:
        if h_sut == 6: tahta[h_sat][5] = tahta[h_sat][7]; tahta[h_sat][7] = ' '
        elif h_sut == 2: tahta[h_sat][3] = tahta[h_sat][0]; tahta[h_sat][0] = ' '

    # TAŞI HEDEFE KOY
    tahta[h_sat][h_sut] = terfi.upper() if (secilen.upper() == 'P' and terfi and beyaz_sirasi) else terfi.lower() if (secilen.upper() == 'P' and terfi and not beyaz_sirasi) else secilen
    tahta[b_sat][b_sut] = ' '

    # BAYRAKLARI GÜNCELLE
    if secilen == 'K': beyaz_sah_oynadi = True
    elif secilen == 'k': siyah_sah_oynadi = True
    elif secilen == 'R':
        if b_sut == 0: beyaz_kale_sol_oynadi = True
        if b_sut == 7: beyaz_kale_sag_oynadi = True
    elif secilen == 'r':
        if b_sut == 0: siyah_kale_sol_oynadi = True
        if b_sut == 7: siyah_kale_sag_oynadi = True

    beyaz_sirasi = not beyaz_sirasi
    anahtar = tahta_durum_anahtari(beyaz_sirasi)
    konum_gecmisi[anahtar] = konum_gecmisi.get(anahtar, 0) + 1

    sah_r, sah_c = sah_konumu_bul(beyaz_sirasi)
    sah_tehdidi = tehdit_altinda_mi(sah_r, sah_c, not beyaz_sirasi) if sah_r != -1 else False
    kalan = tum_gecerli_hamlelerin_sayisi(beyaz_sirasi)

    mesaj = ""
    if kalan == 0:
        if sah_tehdidi: mesaj = f"ŞAH MAT! {'Siyah' if not beyaz_sirasi else 'Beyaz'} Kazandı!"; mac_kaydet("vahit", beyaz_skor, siyah_skor, 'Siyah' if not beyaz_sirasi else 'Beyaz')
        else: mesaj = "PAT! Oyun Berabere."; mac_kaydet("vahit", beyaz_skor, siyah_skor, "BERABERE")
    elif elli_hamle_sayaci >= 100: mesaj = "50 Hamle Kuralı - Berabere"
    
    return jsonify({'success': True, 'mesaj': mesaj})

@app.route('/api/reset', methods=['POST'])
def api_reset():
    oyunu_sifirla()
    return jsonify({'success': True})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
