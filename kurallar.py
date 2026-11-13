"""Satranç kural motoru.

Durum (d) bir sözlüktür:
    tahta     : 8x8 liste, ' ' boş; büyük harf beyaz, küçük harf siyah. Satır 0 = 8. sıra
    gecerken  : geçerken alınabilecek kare [satir, sutun] veya None
    b_sah, s_sah             : şah oynadı mı
    b_k_sol, b_k_sag, ...    : ilgili kale oynadı/yendi mi (rok hakkı yok)
Bu modül veritabanından ve web'den bağımsızdır; perft testleriyle doğrulanmıştır.
"""

ROK_ANAHTARLARI = ('b_sah', 'b_k_sol', 'b_k_sag', 's_sah', 's_k_sol', 's_k_sag')
SEMBOLLER = {'K': '♔', 'Q': '♕', 'R': '♖', 'B': '♗', 'N': '♘', 'P': '♙',
             'k': '♚', 'q': '♛', 'r': '♜', 'b': '♝', 'n': '♞', 'p': '♟'}
TAS_PUANLARI = {'P': 1, 'N': 3, 'B': 3, 'R': 5, 'Q': 9, 'K': 0}
SUTUNLAR = 'abcdefgh'


def baslangic_durumu():
    d = {
        'tahta': [list('rnbqkbnr'), list('pppppppp')] + [[' '] * 8 for _ in range(4)] +
                 [list('PPPPPPPP'), list('RNBQKBNR')],
        'gecerken': None,
    }
    for k in ROK_ANAHTARLARI:
        d[k] = False
    return d


def durum_kopyala(d):
    k = {'tahta': [s[:] for s in d['tahta']], 'gecerken': d['gecerken']}
    for a in ROK_ANAHTARLARI:
        k[a] = d[a]
    return k


def _ep_mi(d, sat, sut):
    ep = d.get('gecerken')
    return bool(ep) and ep[0] == sat and ep[1] == sut


def kare_adi(sat, sut):
    return f"{SUTUNLAR[sut]}{8 - sat}"


# ---------------------------------------------------------------------
# Tehdit ve hamle geçerliliği
# ---------------------------------------------------------------------
def yol_acik_mi(tahta, b_sat, b_sut, h_sat, h_sut):
    adim_sat = 0 if h_sat == b_sat else (1 if h_sat > b_sat else -1)
    adim_sut = 0 if h_sut == b_sut else (1 if h_sut > b_sut else -1)
    g_sat, g_sut = b_sat + adim_sat, b_sut + adim_sut
    while (g_sat, g_sut) != (h_sat, h_sut):
        if tahta[g_sat][g_sut] != ' ':
            return False
        g_sat += adim_sat
        g_sut += adim_sut
    return True


def sah_konumu_bul(tahta, beyaz_mi):
    aranan = 'K' if beyaz_mi else 'k'
    for r in range(8):
        for c in range(8):
            if tahta[r][c] == aranan:
                return r, c
    return -1, -1


def tehdit_altinda_mi(tahta, satir, sutun, saldirgan_beyaz_mi):
    for r in range(8):
        for c in range(8):
            tas = tahta[r][c]
            if tas == ' ' or tas.isupper() != saldirgan_beyaz_mi or (r, c) == (satir, sutun):
                continue
            tip = tas.upper()
            df_sat, df_sut = abs(satir - r), abs(sutun - c)
            if tip == 'P':
                yon = -1 if saldirgan_beyaz_mi else 1
                if satir - r == yon and df_sut == 1:
                    return True
            elif tip == 'N':
                if (df_sat == 2 and df_sut == 1) or (df_sat == 1 and df_sut == 2):
                    return True
            elif tip == 'B':
                if df_sat == df_sut and yol_acik_mi(tahta, r, c, satir, sutun):
                    return True
            elif tip == 'R':
                if (r == satir or c == sutun) and yol_acik_mi(tahta, r, c, satir, sutun):
                    return True
            elif tip == 'Q':
                if (r == satir or c == sutun or df_sat == df_sut) and yol_acik_mi(tahta, r, c, satir, sutun):
                    return True
            elif tip == 'K':
                if df_sat <= 1 and df_sut <= 1:
                    return True
    return False


def sah_tehditte_mi(d, beyaz):
    r, c = sah_konumu_bul(d['tahta'], beyaz)
    return r != -1 and tehdit_altinda_mi(d['tahta'], r, c, not beyaz)


def _rok_kontrol(d, beyaz, h_sut):
    tahta = d['tahta']
    sat = 7 if beyaz else 0
    rakip = not beyaz
    if d['b_sah' if beyaz else 's_sah'] or tehdit_altinda_mi(tahta, sat, 4, rakip):
        return False
    kale = 'R' if beyaz else 'r'
    if h_sut == 6:
        if d['b_k_sag' if beyaz else 's_k_sag'] or tahta[sat][7] != kale:
            return False
        if tahta[sat][5] != ' ' or tahta[sat][6] != ' ':
            return False
        return not (tehdit_altinda_mi(tahta, sat, 5, rakip) or tehdit_altinda_mi(tahta, sat, 6, rakip))
    if h_sut == 2:
        if d['b_k_sol' if beyaz else 's_k_sol'] or tahta[sat][0] != kale:
            return False
        if tahta[sat][1] != ' ' or tahta[sat][2] != ' ' or tahta[sat][3] != ' ':
            return False
        return not (tehdit_altinda_mi(tahta, sat, 3, rakip) or tehdit_altinda_mi(tahta, sat, 2, rakip))
    return False


def kural_kontrol(d, tas, b_sat, b_sut, h_sat, h_sut):
    """Taşın hareket kuralına uyuyor mu (şahın açıkta kalması burada kontrol edilmez)."""
    tahta = d['tahta']
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
            if h_sat - b_sat == yon:
                return True
            if b_sat == baslangic and h_sat - b_sat == 2 * yon and tahta[b_sat + yon][b_sut] == ' ':
                return True
        if df_sut == 1 and h_sat - b_sat == yon:
            return hedef != ' ' or _ep_mi(d, h_sat, h_sut)
        return False
    if tip == 'R':
        return (b_sat == h_sat or b_sut == h_sut) and yol_acik_mi(tahta, b_sat, b_sut, h_sat, h_sut)
    if tip == 'B':
        return df_sat == df_sut and yol_acik_mi(tahta, b_sat, b_sut, h_sat, h_sut)
    if tip == 'Q':
        return (b_sat == h_sat or b_sut == h_sut or df_sat == df_sut) and yol_acik_mi(tahta, b_sat, b_sut, h_sat, h_sut)
    if tip == 'N':
        return (df_sat == 2 and df_sut == 1) or (df_sat == 1 and df_sut == 2)
    if tip == 'K':
        if df_sat <= 1 and df_sut <= 1:
            return True
        if df_sat == 0 and df_sut == 2 and (b_sat, b_sut) == ((7, 4) if beyaz_mi else (0, 4)):
            return _rok_kontrol(d, beyaz_mi, h_sut)
    return False


def gecerli_hamleleri_bul(d, b_sat, b_sut, b_sirasi):
    """Seçilen taşın yasal hedef kareleri: [[satir, sutun], ...]"""
    tahta = d['tahta']
    secilen = tahta[b_sat][b_sut]
    if secilen == ' ' or secilen.isupper() != b_sirasi:
        return []
    hamleler = []
    yon = -1 if b_sirasi else 1
    for h_sat in range(8):
        for h_sut in range(8):
            hedef = tahta[h_sat][h_sut]
            if hedef != ' ' and hedef.isupper() == b_sirasi:
                continue
            if not kural_kontrol(d, secilen, b_sat, b_sut, h_sat, h_sut):
                continue
            # Hamleyi geçici olarak yap, kendi şahı tehditte mi bak, geri al
            ep = secilen.upper() == 'P' and h_sut != b_sut and hedef == ' '
            alinan_ep = ' '
            if ep:
                alinan_ep = tahta[h_sat - yon][h_sut]
                tahta[h_sat - yon][h_sut] = ' '
            tahta[h_sat][h_sut] = secilen
            tahta[b_sat][b_sut] = ' '
            roklu = secilen.upper() == 'K' and abs(h_sut - b_sut) == 2
            if roklu:
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


def tum_hamleler(d, beyaz):
    """Tüm yasal hamleler: [(b_sat, b_sut, h_sat, h_sut), ...]"""
    tahta = d['tahta']
    sonuc = []
    for r in range(8):
        for c in range(8):
            t = tahta[r][c]
            if t != ' ' and t.isupper() == beyaz:
                for h in gecerli_hamleleri_bul(d, r, c, beyaz):
                    sonuc.append((r, c, h[0], h[1]))
    return sonuc


def hamle_var_mi(d, beyaz):
    tahta = d['tahta']
    for r in range(8):
        for c in range(8):
            t = tahta[r][c]
            if t != ' ' and t.isupper() == beyaz and gecerli_hamleleri_bul(d, r, c, beyaz):
                return True
    return False


# ---------------------------------------------------------------------
# Hamle uygulama
# ---------------------------------------------------------------------
def hamle_uygula(d, b_sat, b_sut, h_sat, h_sut, terfi=None):
    """Yasal olduğu bilinen hamleyi d üzerinde yapar.
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
            yeni_ep = [b_sat + yon, b_sut]
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
        secim = terfi_normalle(terfi)
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


def terfi_normalle(terfi):
    secim = str(terfi).upper() if terfi else 'Q'
    return secim if secim in ('Q', 'R', 'B', 'N') else 'Q'


# ---------------------------------------------------------------------
# Notasyon (SAN), konum anahtarı, materyal
# ---------------------------------------------------------------------
def san_uret(d, b_sat, b_sut, h_sat, h_sut, terfi=None):
    """Hamleyi yapmadan önce çağrılır; standart cebirsel notasyonu döndürür (Nf3, exd5, O-O, e8=Q+)."""
    tahta = d['tahta']
    tas = tahta[b_sat][b_sut]
    tip = tas.upper()
    beyaz = tas.isupper()
    alma = tahta[h_sat][h_sut] != ' ' or (tip == 'P' and b_sut != h_sut)

    if tip == 'K' and abs(h_sut - b_sut) == 2:
        san = 'O-O' if h_sut == 6 else 'O-O-O'
    elif tip == 'P':
        san = (SUTUNLAR[b_sut] + 'x' if alma else '') + kare_adi(h_sat, h_sut)
        if h_sat in (0, 7):
            san += '=' + terfi_normalle(terfi)
    else:
        # Aynı hedefe gidebilen aynı türden başka taş varsa ayırt et
        digerleri = []
        for r in range(8):
            for c in range(8):
                if (r, c) != (b_sat, b_sut) and tahta[r][c] == tas and [h_sat, h_sut] in gecerli_hamleleri_bul(d, r, c, beyaz):
                    digerleri.append((r, c))
        ayirt = ''
        if digerleri:
            if all(c != b_sut for _, c in digerleri):
                ayirt = SUTUNLAR[b_sut]
            elif all(r != b_sat for r, _ in digerleri):
                ayirt = str(8 - b_sat)
            else:
                ayirt = kare_adi(b_sat, b_sut)
        san = tip + ayirt + ('x' if alma else '') + kare_adi(h_sat, h_sut)

    k = durum_kopyala(d)
    hamle_uygula(k, b_sat, b_sut, h_sat, h_sut, terfi)
    if sah_tehditte_mi(k, not beyaz):
        san += '#' if not hamle_var_mi(k, not beyaz) else '+'
    return san


def uci(b_sat, b_sut, h_sat, h_sut, terfi=None, tas=''):
    s = kare_adi(b_sat, b_sut) + kare_adi(h_sat, h_sut)
    if tas.upper() == 'P' and h_sat in (0, 7):
        s += terfi_normalle(terfi).lower()
    return s


def uci_coz(metin):
    """'e2e4' / 'e7e8q' -> (b_sat, b_sut, h_sat, h_sut, terfi)"""
    b_sut, b_sat = SUTUNLAR.index(metin[0]), 8 - int(metin[1])
    h_sut, h_sat = SUTUNLAR.index(metin[2]), 8 - int(metin[3])
    terfi = metin[4].upper() if len(metin) > 4 else None
    return b_sat, b_sut, h_sat, h_sut, terfi


def konum_anahtari(d, beyaz_sirasi):
    """Konum tekrarı için anahtar. Geçerken karesi sadece gerçekten alınabiliyorsa dahil edilir."""
    t_str = "".join("".join(s) for s in d['tahta'])
    r_str = "".join('1' if d[k] else '0' for k in ROK_ANAHTARLARI)
    ep = d.get('gecerken')
    if ep:
        piyon = 'P' if beyaz_sirasi else 'p'
        satir = ep[0] + (1 if beyaz_sirasi else -1)
        if not any(0 <= ep[1] + dx < 8 and d['tahta'][satir][ep[1] + dx] == piyon for dx in (-1, 1)):
            ep = None
    return f"{t_str}_{int(beyaz_sirasi)}_{r_str}_{ep[0] if ep else ''}{ep[1] if ep else ''}"


def sadece_sah_var_mi(tahta, beyaz_mi):
    for satir in tahta:
        for t in satir:
            if t != ' ' and t.isupper() == beyaz_mi and t.upper() != 'K':
                return False
    return True


def yetersiz_materyal_mi(tahta):
    taslar, fil_renkleri = [], []
    for r in range(8):
        for c in range(8):
            t = tahta[r][c]
            if t != ' ' and t.upper() != 'K':
                taslar.append(t.upper())
                if t.upper() == 'B':
                    fil_renkleri.append((r + c) % 2)
    if not taslar:
        return True
    if len(taslar) == 1 and taslar[0] in ('N', 'B'):
        return True
    # Sadece filler kaldıysa ve hepsi aynı renk karedeyse mat imkânsız
    return all(t == 'B' for t in taslar) and len(set(fil_renkleri)) == 1


def tahta_metni(tahta):
    return "".join("".join(s) for s in tahta)
