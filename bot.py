"""Yapay zeka rakip: alfa-beta budamalı negamax + konum tabloları."""
import random
import time

from kurallar import tum_hamleler, hamle_uygula, durum_kopyala, sah_konumu_bul, tehdit_altinda_mi

DEGERLER = {'P': 100, 'N': 320, 'B': 330, 'R': 500, 'Q': 900, 'K': 0}
# Beyaz açısından konum tabloları (satır 0 = 8. sıra)
PST = {
    'P': [[0] * 8, [50] * 8, [10, 10, 20, 30, 30, 20, 10, 10], [5, 5, 10, 25, 25, 10, 5, 5],
          [0, 0, 0, 20, 20, 0, 0, 0], [5, -5, -10, 0, 0, -10, -5, 5], [5, 10, 10, -20, -20, 10, 10, 5], [0] * 8],
    'N': [[-50, -40, -30, -30, -30, -30, -40, -50], [-40, -20, 0, 0, 0, 0, -20, -40], [-30, 0, 10, 15, 15, 10, 0, -30],
          [-30, 5, 15, 20, 20, 15, 5, -30], [-30, 0, 15, 20, 20, 15, 0, -30], [-30, 5, 10, 15, 15, 10, 5, -30],
          [-40, -20, 0, 5, 5, 0, -20, -40], [-50, -40, -30, -30, -30, -30, -40, -50]],
    'B': [[-20, -10, -10, -10, -10, -10, -10, -20], [-10, 0, 0, 0, 0, 0, 0, -10], [-10, 0, 5, 10, 10, 5, 0, -10],
          [-10, 5, 5, 10, 10, 5, 5, -10], [-10, 0, 10, 10, 10, 10, 0, -10], [-10, 10, 10, 10, 10, 10, 10, -10],
          [-10, 5, 0, 0, 0, 0, 5, -10], [-20, -10, -10, -10, -10, -10, -10, -20]],
    'R': [[0] * 8, [5, 10, 10, 10, 10, 10, 10, 5]] + [[-5, 0, 0, 0, 0, 0, 0, -5]] * 5 + [[0, 0, 0, 5, 5, 0, 0, 0]],
    'Q': [[-20, -10, -10, -5, -5, -10, -10, -20], [-10, 0, 0, 0, 0, 0, 0, -10], [-10, 0, 5, 5, 5, 5, 0, -10],
          [-5, 0, 5, 5, 5, 5, 0, -5], [0, 0, 5, 5, 5, 5, 0, -5], [-10, 5, 5, 5, 5, 5, 0, -10],
          [-10, 0, 5, 0, 0, 0, 0, -10], [-20, -10, -10, -5, -5, -10, -10, -20]],
    'K': [[-30, -40, -40, -50, -50, -40, -40, -30]] * 4 + [[-20, -30, -30, -40, -40, -30, -30, -20],
          [-10, -20, -20, -20, -20, -20, -20, -10], [20, 20, 0, 0, 0, 0, 20, 20], [20, 30, 10, 0, 0, 10, 30, 20]],
}
MAT_SKORU = 100000
SEVIYELER = ('kolay', 'orta', 'zor')


class SureDoldu(Exception):
    pass


def degerlendir(tahta):
    """Pozitif = beyaz önde (santipiyon)."""
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


def _sirala(d, hamleler):
    tahta = d['tahta']

    def anahtar(m):
        hedef = tahta[m[2]][m[3]]
        if hedef == ' ':
            return 0
        # Önce değerli taşı ucuz taşla alan hamleler (MVV-LVA)
        return -(DEGERLER.get(hedef.upper(), 0) * 10 - DEGERLER[tahta[m[0]][m[1]].upper()] // 10)
    return sorted(hamleler, key=anahtar)


def _negamax(d, beyaz, derinlik, alpha, beta, ply, bitis):
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
        skor = -_negamax(k, not beyaz, derinlik - 1, -beta, -alpha, ply + 1, bitis)
        if skor > en_iyi:
            en_iyi = skor
        if skor > alpha:
            alpha = skor
        if alpha >= beta:
            break
    return en_iyi


def hamle_sec(d, beyaz, zorluk, kalan_sure=None):
    """Botun hamlesi: (b_sat, b_sut, h_sat, h_sut) veya None."""
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

    maks_derinlik, sure_limit = (2, 1.2) if zorluk == 'orta' else (4, 2.0)
    if kalan_sure is not None:
        # Kalan sürenin en fazla ~1/30'unu harca; kısa oyunlarda süreden kaybetmesin
        sure_limit = max(0.2, min(sure_limit, kalan_sure / 30))
    bitis = time.time() + sure_limit
    random.shuffle(hamleler)  # aynı oyunu hep aynı oynamasın
    en_iyi = hamleler[0]
    for derinlik in range(1, maks_derinlik + 1):
        try:
            alpha = -MAT_SKORU * 2
            bu_tur = None
            for m in _sirala(d, hamleler):
                k = durum_kopyala(d)
                hamle_uygula(k, *m)
                skor = -_negamax(k, not beyaz, derinlik - 1, -MAT_SKORU * 2, -alpha, 1, bitis)
                if bu_tur is None or skor > alpha:
                    alpha = skor
                    bu_tur = m
            en_iyi = bu_tur
            hamleler.remove(en_iyi)
            hamleler.insert(0, en_iyi)  # bir sonraki derinlikte önce en iyiyi dene
            if alpha >= MAT_SKORU - 100:
                break
        except SureDoldu:
            break
    return en_iyi


def beraberlik_kabul_eder_mi(d, bot_beyaz):
    """Bot kendi açısından belirgin şekilde gerideyse beraberliği kabul eder."""
    skor = degerlendir(d['tahta']) * (1 if bot_beyaz else -1)
    return skor < -150
