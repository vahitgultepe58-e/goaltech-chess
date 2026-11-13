"""Bir oyun odasının akışı: hamleler, satranç saati, geri alma, teslim/beraberlik ve oyun sonu.

Oda durumu JSON'a çevrilebilir düz bir sözlüktür (veritabanında saklanır).
Bu modülde veritabanı ya da web kodu yoktur; fonksiyonlar odayı yerinde değiştirir.
"""
import copy
import random
import string
import time

import kurallar as K

SURE_SECENEKLERI = ('1+0', '3+0', '3+2', '5+0', '5+3', '10+0', '10+5', '15+10')
VARSAYILAN_SURE = '3+0'
TARAFLAR = ('beyaz', 'siyah')
SOHBET_SINIRI = 60


def sure_coz(metin):
    """'3+2' -> (180 saniye, 2 saniye artış). Geçersizse varsayılan."""
    if metin not in SURE_SECENEKLERI:
        metin = VARSAYILAN_SURE
    dk, artis = metin.split('+')
    return int(dk) * 60, int(artis)


def yeni_oda_id():
    return ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))


def _bos_oyuncu():
    return {'id': '', 'ad': '', 'kullanici_id': None, 'elo': None, 'katildi': False}


def yeni_oda(tur='arkadas', sure=VARSAYILAN_SURE, bot_zorluk=None, simdi=None):
    """tur: 'arkadas' (davet linki), 'lobi' (eşleşme), 'bot'"""
    simdi = simdi or time.time()
    toplam, artis = sure_coz(sure)
    o = {
        'tur': tur,
        'bot': bot_zorluk if tur == 'bot' else None,
        'puanli': False,
        'sure_ayari': sure if sure in SURE_SECENEKLERI else VARSAYILAN_SURE,
        'artis': artis,
        'oyuncular': {'beyaz': _bos_oyuncu(), 'siyah': _bos_oyuncu()},
        'sohbet': [],
        'sohbet_no': 0,
        'olusturma': simdi,
    }
    if tur == 'bot':
        o['oyuncular']['siyah'].update({'ad': 'Bot', 'katildi': True, 'id': 'bot'})
    oyunu_baslat(o, toplam, simdi)
    return o


def oyunu_baslat(o, toplam=None, simdi=None):
    """Tahtayı ve oyun durumunu sıfırlar; oyuncular, ayarlar ve sohbet korunur."""
    if toplam is None:
        toplam, o['artis'] = sure_coz(o['sure_ayari'])
    o.update({
        'd': K.baslangic_durumu(),
        'beyaz_sirasi': True,
        'skor': {'beyaz': 0, 'siyah': 0},
        'alinan': {'beyaz': [], 'siyah': []},   # 'beyaz' = beyazın yediği taşlar
        'elli': 0,
        'konumlar': {},
        'gecmis': [],
        'hamleler': [],                          # [{'uci': 'e2e4', 'san': 'e4'}]
        'son_hamle': None,
        'sure': {'beyaz': float(toplam), 'siyah': float(toplam)},
        'son_zaman': simdi or time.time(),
        'basladi': False,
        'bitti': False,
        'sonuc': None,                           # '1-0', '0-1', '1/2-1/2'
        'sebep': None,
        'mesaj': '',
        'istek': None,                           # {'tip': 'geri'|'yeni'|'berabere', 'taraf': ..., 'no': ...}
        'son_hamle_zamani': 0,
        'bot_basladi': 0,
        'elo_degisim': None,
        'mac_id': None,
    })
    o['konumlar'][K.konum_anahtari(o['d'], True)] = 1


def sira_taraf(o):
    return 'beyaz' if o['beyaz_sirasi'] else 'siyah'


def rakip(taraf):
    return 'siyah' if taraf == 'beyaz' else 'beyaz'


# ---------------------------------------------------------------------
# Saat
# ---------------------------------------------------------------------
def anlik_sureler(o, simdi=None):
    """Şu anki kalan süreler (sıradaki tarafın saati işliyorsa düşülmüş halde)."""
    simdi = simdi or time.time()
    s = dict(o['sure'])
    if o['basladi'] and not o['bitti']:
        t = sira_taraf(o)
        s[t] = max(0.0, s[t] - (simdi - o['son_zaman']))
    return s


def sure_kontrol(o, simdi=None):
    """Sıradaki tarafın süresi bittiyse oyunu bitirir. Oyun bittiyse True."""
    if o['bitti'] or not o['basladi']:
        return False
    t = sira_taraf(o)
    if anlik_sureler(o, simdi)[t] > 0:
        return False
    o['sure'][t] = 0.0
    kazanan = rakip(t)
    if K.sadece_sah_var_mi(o['d']['tahta'], kazanan == 'beyaz'):
        oyunu_bitir(o, '1/2-1/2', 'sure_materyal', f"{t.capitalize()}ın süresi bitti, rakipte mat materyali yok. Berabere.")
    else:
        oyunu_bitir(o, '1-0' if kazanan == 'beyaz' else '0-1', 'sure', f"{t.capitalize()}ın süresi bitti! {kazanan.capitalize()} kazandı.")
    return True


# ---------------------------------------------------------------------
# Hamle
# ---------------------------------------------------------------------
_GECMIS_ALANLARI = ('d', 'beyaz_sirasi', 'skor', 'alinan', 'elli', 'sure', 'son_hamle', 'basladi')


def hamle_gecerli_mi(o, b_sat, b_sut, h_sat, h_sut):
    return [h_sat, h_sut] in K.gecerli_hamleleri_bul(o['d'], b_sat, b_sut, o['beyaz_sirasi'])


def hamle_yap(o, b_sat, b_sut, h_sat, h_sut, terfi=None, simdi=None):
    """Geçerliliği kontrol edilmiş hamleyi uygular, saati ilerletir, oyun sonunu denetler."""
    simdi = simdi or time.time()
    d = o['d']
    tas = d['tahta'][b_sat][b_sut]
    t = sira_taraf(o)

    o['gecmis'].append({k: copy.deepcopy(o[k]) for k in _GECMIS_ALANLARI})
    san = K.san_uret(d, b_sat, b_sut, h_sat, h_sut, terfi)
    o['hamleler'].append({'uci': K.uci(b_sat, b_sut, h_sat, h_sut, terfi, tas), 'san': san})

    # Saat: hamle yapanın süresinden geçen zamanı düş, artışı ekle
    if o['basladi']:
        o['sure'][t] = max(0.0, o['sure'][t] - (simdi - o['son_zaman'])) + o['artis']
    elif t == 'beyaz':
        o['basladi'] = True   # saat beyazın ilk hamlesiyle başlar (siyahın saati işlemeye başlar)
    o['son_zaman'] = simdi
    o['son_hamle_zamani'] = simdi
    o['mesaj'] = ''
    o['istek'] = None

    alinan, ek = K.hamle_uygula(d, b_sat, b_sut, h_sat, h_sut, terfi)
    if alinan:
        o['skor'][t] += K.TAS_PUANLARI.get(alinan.upper(), 0)
        o['alinan'][t].append(K.SEMBOLLER[alinan])
    o['elli'] = 0 if (tas.upper() == 'P' or alinan) else o['elli'] + 1
    o['son_hamle'] = [[[b_sat, b_sut], [h_sat, h_sut]]] + ek
    o['beyaz_sirasi'] = not o['beyaz_sirasi']

    anahtar = K.konum_anahtari(d, o['beyaz_sirasi'])
    o['konumlar'][anahtar] = o['konumlar'].get(anahtar, 0) + 1

    sira_beyaz = o['beyaz_sirasi']
    if not K.hamle_var_mi(d, sira_beyaz):
        if K.sah_tehditte_mi(d, sira_beyaz):
            kazanan = rakip(sira_taraf(o))
            oyunu_bitir(o, '1-0' if kazanan == 'beyaz' else '0-1', 'mat', f"ŞAH MAT! {kazanan.capitalize()} kazandı.")
        else:
            oyunu_bitir(o, '1/2-1/2', 'pat', "PAT! Oyun berabere.")
    elif o['elli'] >= 100:
        oyunu_bitir(o, '1/2-1/2', 'elli', "50 hamle kuralı nedeniyle berabere.")
    elif o['konumlar'][anahtar] >= 3:
        oyunu_bitir(o, '1/2-1/2', 'tekrar', "3 kez konum tekrarı nedeniyle berabere.")
    elif K.yetersiz_materyal_mi(d['tahta']):
        oyunu_bitir(o, '1/2-1/2', 'materyal', "Yetersiz materyal nedeniyle berabere.")
    return san


def oyunu_bitir(o, sonuc, sebep, mesaj):
    if o['bitti']:
        return
    o['bitti'] = True
    o['sonuc'] = sonuc
    o['sebep'] = sebep
    o['mesaj'] = mesaj
    o['istek'] = None


def teslim_ol(o, taraf):
    kazanan = rakip(taraf)
    oyunu_bitir(o, '1-0' if kazanan == 'beyaz' else '0-1', 'teslim',
                f"{taraf.capitalize()} teslim oldu. {kazanan.capitalize()} kazandı.")


def berabere_bitir(o):
    oyunu_bitir(o, '1/2-1/2', 'anlasma', "Karşılıklı anlaşmayla berabere.")


def geri_al(o, adet, simdi=None):
    """Son `adet` yarım hamleyi geri alır."""
    for _ in range(adet):
        if not o['gecmis']:
            break
        anahtar = K.konum_anahtari(o['d'], o['beyaz_sirasi'])
        if o['konumlar'].get(anahtar, 0) > 1:
            o['konumlar'][anahtar] -= 1
        else:
            o['konumlar'].pop(anahtar, None)
        eski = o['gecmis'].pop()
        for k in _GECMIS_ALANLARI:
            o[k] = eski[k]
        o['hamleler'].pop()
    o['son_zaman'] = simdi or time.time()
    o['bitti'] = False
    o['sonuc'] = o['sebep'] = None
    o['mesaj'] = ''
    o['istek'] = None


def geri_alma_adedi(o, taraf):
    """İsteyen tarafın son hamlesini geri almak için kaç yarım hamle gerekir (0 = mümkün değil)."""
    adet = 2 if sira_taraf(o) == taraf else 1
    return adet if len(o['gecmis']) >= adet else 0


# ---------------------------------------------------------------------
# Sohbet ve istemci görünümü
# ---------------------------------------------------------------------
def sohbet_ekle(o, taraf, metin):
    o['sohbet_no'] += 1
    o['sohbet'].append({'no': o['sohbet_no'], 'taraf': taraf, 'metin': metin})
    del o['sohbet'][:-SOHBET_SINIRI]


def taraf_bul(o, kimlik):
    for t in TARAFLAR:
        if kimlik and o['oyuncular'][t]['id'] == kimlik:
            return t
    return None


def gorunum(o, surum, baglantilar, simdi=None):
    """Tarayıcıya gönderilen oda bilgisi."""
    simdi = simdi or time.time()
    d = o['d']
    sureler = anlik_sureler(o, simdi)
    oyuncular = {}
    for t in TARAFLAR:
        p = o['oyuncular'][t]
        oyuncular[t] = {'ad': p['ad'], 'elo': p['elo'], 'katildi': p['katildi'],
                        'bagli': (t == 'siyah' and o['tur'] == 'bot') or bool(baglantilar.get(t)),
                        'uye': p['kullanici_id'] is not None}
    return {
        'surum': surum,
        'tur': o['tur'], 'bot': o['bot'], 'puanli': o['puanli'],
        'sure_ayari': o['sure_ayari'], 'artis': o['artis'],
        'tahta': d['tahta'],
        'beyaz_sirasi': o['beyaz_sirasi'],
        'sah_tehdit': K.sah_tehditte_mi(d, o['beyaz_sirasi']),
        'skor': o['skor'], 'alinan': o['alinan'],
        'sure': {t: round(sureler[t], 1) for t in TARAFLAR},
        'saat_isliyor': o['basladi'] and not o['bitti'],
        'hamleler': [h['san'] for h in o['hamleler']],
        'son_hamle': o['son_hamle'],
        'bitti': o['bitti'], 'sonuc': o['sonuc'], 'sebep': o['sebep'], 'mesaj': o['mesaj'],
        'istek': o['istek'],
        'oyuncular': oyuncular,
        'bot_dusunuyor': o['tur'] == 'bot' and not o['bitti'] and not o['beyaz_sirasi'],
        'sohbet': o['sohbet'],
        'elo_degisim': o['elo_degisim'],
        'mac_id': o['mac_id'],
    }
