"""Goaltech Chess — Flask sunucusu.

Dosyalar:
    kurallar.py  satranç kuralları (perft testli)
    bot.py       yapay zeka rakip
    oyun.py      oda/oyun akışı ve satranç saati
    depo.py      SQLite veri katmanı
    index.html   arayüz
"""
import os
import random
import re
import secrets
import threading
import time

from flask import Flask, jsonify, request, send_file, session
from werkzeug.security import check_password_hash, generate_password_hash

import bot
import depo
import kurallar as K
import oyun

KLASOR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)


def _gizli_anahtar():
    anahtar = os.environ.get('GOALTECH_SECRET')
    if anahtar:
        return anahtar
    yol = os.path.join(KLASOR, '.gizli_anahtar')
    try:
        with open(yol) as f:
            return f.read().strip()
    except FileNotFoundError:
        anahtar = secrets.token_hex(32)
        with open(yol, 'w') as f:
            f.write(anahtar)
        return anahtar


app.config.update(
    SECRET_KEY=_gizli_anahtar(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 60,
)
depo.kur()

BOT_BEKLEME = 0.5          # bot hamlesinden önce kısa "düşünme" arası
ILK_HAMLE_SURESI = 45      # lobi oyununda ilk hamle bu sürede yapılmazsa oyun iptal
AD_DESENI = re.compile(r'^[A-Za-z0-9_çğıöşüÇĞİÖŞÜ]{3,20}$')


def hata(mesaj, kod=200, **ek):
    return jsonify({'success': False, 'error': mesaj, **ek}), kod


def tamam(**ek):
    return jsonify({'success': True, **ek})


def veri():
    return request.get_json(silent=True) or {}


def kimlik():
    return (request.args.get('id') or '')[:40]


def oda_id():
    return (request.args.get('oda') or '')[:16]


def aktif_kullanici():
    kid = session.get('kid')
    return depo.kullanici_id_ile(kid) if kid else None


def misafir_adi():
    ad = (veri().get('ad') or request.args.get('ad') or '').strip()[:20]
    return ad or 'Misafir'


@app.before_request
def _ara_sira_temizle():
    if random.random() < 0.01:
        try:
            depo.temizlik()
        except Exception:
            pass


@app.after_request
def _onbellek_yok(yanit):
    if request.path.startswith('/api/'):
        yanit.headers['Cache-Control'] = 'no-store'
    return yanit


# =====================================================================
# Sayfa
# =====================================================================
@app.route('/')
def ana_sayfa():
    yanit = send_file(os.path.join(KLASOR, 'index.html'))
    yanit.headers['Cache-Control'] = 'no-cache'
    return yanit


# =====================================================================
# Hesaplar
# =====================================================================
_basarisiz_girisler = {}
_giris_kilit = threading.Lock()


def _kullanici_ozeti(k):
    return None if not k else {'ad': k['ad'], 'elo': k['elo'], 'oyun': k['oyun'], 'galibiyet': k['galibiyet'],
                               'maglubiyet': k['maglubiyet'], 'beraberlik': k['beraberlik']}


@app.route('/api/ben')
def api_ben():
    return tamam(kullanici=_kullanici_ozeti(aktif_kullanici()))


@app.route('/api/kayit', methods=['POST'])
def api_kayit():
    ad = (veri().get('ad') or '').strip()
    sifre = veri().get('sifre') or ''
    if not AD_DESENI.match(ad):
        return hata('Kullanıcı adı 3-20 karakter olmalı; harf, rakam ve _ kullanılabilir.')
    if len(sifre) < 6:
        return hata('Şifre en az 6 karakter olmalı.')
    kid = depo.kullanici_ekle(ad, generate_password_hash(sifre))
    if not kid:
        return hata('Bu kullanıcı adı alınmış.')
    session.clear()
    session.permanent = True
    session['kid'] = kid
    return tamam(kullanici=_kullanici_ozeti(depo.kullanici_id_ile(kid)))


@app.route('/api/giris', methods=['POST'])
def api_giris():
    ad = (veri().get('ad') or '').strip()
    sifre = veri().get('sifre') or ''
    anahtar = (request.remote_addr or '', ad.lower())
    simdi = time.time()
    with _giris_kilit:
        denemeler = [t for t in _basarisiz_girisler.get(anahtar, []) if simdi - t < 600]
        _basarisiz_girisler[anahtar] = denemeler
    if len(denemeler) >= 8:
        return hata('Çok fazla hatalı deneme. 10 dakika sonra tekrar dene.')
    k = depo.kullanici_ad_ile(ad)
    if not k or not check_password_hash(k['sifre_hash'], sifre):
        with _giris_kilit:
            _basarisiz_girisler.setdefault(anahtar, []).append(simdi)
        return hata('Kullanıcı adı veya şifre hatalı.')
    session.clear()
    session.permanent = True
    session['kid'] = k['id']
    return tamam(kullanici=_kullanici_ozeti(k))


@app.route('/api/cikis', methods=['POST'])
def api_cikis():
    session.clear()
    return tamam()


@app.route('/api/liderlik')
def api_liderlik():
    return tamam(liste=depo.liderlik())


@app.route('/api/profil/<ad>')
def api_profil(ad):
    k = depo.kullanici_ad_ile(ad)
    if not k:
        return hata('Kullanıcı bulunamadı.', 404)
    return tamam(kullanici=_kullanici_ozeti(k), maclar=depo.kullanici_maclari(k['id']))


@app.route('/api/mac/<int:mid>')
def api_mac(mid):
    m = depo.mac(mid)
    if not m:
        return hata('Maç bulunamadı.', 404)
    d = K.baslangic_durumu()
    tahtalar, son = [K.tahta_metni(d['tahta'])], [None]
    for u in (m['uci'] or '').split():
        b_sat, b_sut, h_sat, h_sut, terfi = K.uci_coz(u)
        K.hamle_uygula(d, b_sat, b_sut, h_sat, h_sut, terfi)
        tahtalar.append(K.tahta_metni(d['tahta']))
        son.append([[b_sat, b_sut], [h_sat, h_sut]])
    alanlar = ('id', 'beyaz_ad', 'siyah_ad', 'sonuc', 'sebep', 'sure_ayari', 'tur', 'bot_zorluk', 'puanli',
               'beyaz_elo', 'siyah_elo', 'beyaz_degisim', 'siyah_degisim', 'tarih')
    return tamam(mac={k: m[k] for k in alanlar}, san=(m['san'] or '').split(), tahtalar=tahtalar, son_hamleler=son)


# =====================================================================
# Maç kaydı ve Elo
# =====================================================================
def _beklenen(ra, rb):
    return 1 / (1 + 10 ** ((rb - ra) / 400))


def mac_kaydet_gerekirse(oid):
    """Oyun bittiyse ve henüz kaydedilmediyse maçı kaydeder, puanlıysa Elo'ları günceller (tek işlemde)."""
    def fn(o):
        if not o or not o['bitti'] or o['mac_id'] is not None or o['sonuc'] == '*':
            return None, False
        con = depo.baglanti()
        b, s = o['oyuncular']['beyaz'], o['oyuncular']['siyah']
        puan_b = {'1-0': 1.0, '0-1': 0.0}.get(o['sonuc'], 0.5)
        degisim = {'beyaz': None, 'siyah': None}
        kb = depo.kullanici_id_ile(b['kullanici_id']) if b['kullanici_id'] else None
        ks = depo.kullanici_id_ile(s['kullanici_id']) if s['kullanici_id'] else None
        if o['puanli'] and kb and ks:
            eb = _beklenen(kb['elo'], ks['elo'])
            kfak_b = 40 if kb['oyun'] < 20 else 20
            kfak_s = 40 if ks['oyun'] < 20 else 20
            degisim['beyaz'] = round(kfak_b * (puan_b - eb))
            degisim['siyah'] = round(kfak_s * ((1 - puan_b) - (1 - eb)))
            for k, d, p in ((kb, degisim['beyaz'], puan_b), (ks, degisim['siyah'], 1 - puan_b)):
                sutun = 'galibiyet' if p == 1 else 'maglubiyet' if p == 0 else 'beraberlik'
                con.execute(f"UPDATE kullanicilar SET elo = MAX(100, elo + ?), oyun = oyun + 1, "
                            f"{sutun} = {sutun} + 1 WHERE id = ?", (d, k['id']))
        mid = depo.mac_ekle(con, {
            'oda': o.get('_id'), 'beyaz_id': b['kullanici_id'], 'siyah_id': s['kullanici_id'],
            'beyaz_ad': b['ad'], 'siyah_ad': s['ad'], 'sonuc': o['sonuc'], 'sebep': o['sebep'],
            'uci': ' '.join(h['uci'] for h in o['hamleler']), 'san': ' '.join(h['san'] for h in o['hamleler']),
            'sure_ayari': o['sure_ayari'], 'tur': o['tur'], 'bot_zorluk': o['bot'], 'puanli': int(o['puanli']),
            'beyaz_elo': b['elo'], 'siyah_elo': s['elo'],
            'beyaz_degisim': degisim['beyaz'], 'siyah_degisim': degisim['siyah'], 'tarih': time.time()})
        o['mac_id'] = mid
        if o['puanli']:
            o['elo_degisim'] = degisim
        return mid, True
    depo.oda_guncelle(oid, fn)


# =====================================================================
# Oda oluşturma, katılma, durum
# =====================================================================
def _oyuncuyu_yerlestir(o, taraf, kim, kullanici, ad):
    p = o['oyuncular'][taraf]
    p.update({'id': kim, 'katildi': True,
              'kullanici_id': kullanici['id'] if kullanici else None,
              'elo': kullanici['elo'] if kullanici else None,
              'ad': kullanici['ad'] if kullanici else ad})


@app.route('/api/oda', methods=['POST'])
def api_oda_olustur():
    tur = veri().get('tur')
    if tur not in ('bot', 'arkadas'):
        return hata('Geçersiz oyun türü.')
    zorluk = veri().get('zorluk') if veri().get('zorluk') in bot.SEVIYELER else 'orta'
    o = oyun.yeni_oda(tur, veri().get('sure') or oyun.VARSAYILAN_SURE, zorluk)
    _oyuncuyu_yerlestir(o, 'beyaz', kimlik(), aktif_kullanici(), misafir_adi())
    oid = oyun.yeni_oda_id()
    o['_id'] = oid
    with depo.islem() as con:
        depo.oda_ekle(con, oid, o)
    return tamam(oda=oid)


@app.route('/api/katil', methods=['POST'])
def api_katil():
    oid, kim = oda_id(), kimlik()
    if not kim:
        return hata('Kimlik eksik.')
    kullanici = aktif_kullanici()
    baglantilar = depo.baglanti_durumu(oid)

    def fn(o):
        if o is None:
            return None, False
        t = oyun.taraf_bul(o, kim)
        if t:
            return t, False
        # Aynı hesapla başka sekmeden/cihazdan gelindiyse yerini geri al
        if kullanici:
            for t in oyun.TARAFLAR:
                if o['oyuncular'][t]['kullanici_id'] == kullanici['id']:
                    o['oyuncular'][t]['id'] = kim
                    return t, True
        if o['tur'] == 'arkadas':
            for t in ('siyah', 'beyaz'):
                p = o['oyuncular'][t]
                # Boş yer ya da 30 sn'den uzun süredir bağlı olmayan misafirin yeri
                if not p['katildi'] or (not baglantilar.get(t) and p['kullanici_id'] is None and not kullanici):
                    _oyuncuyu_yerlestir(o, t, kim, kullanici, misafir_adi())
                    return t, True
        return 'izleyici', False

    taraf, _ = depo.oda_guncelle(oid, fn)
    if taraf is None:
        return hata('Oda bulunamadı.', 404, yok=True)
    if taraf != 'izleyici':
        depo.nabiz(oid, taraf)
    return tamam(taraf=taraf)


def _bot_oynat(oid, o, surum):
    """Sıra bottaysa hamlesini hesaplar. Hesap kilit dışında yapılır, sonra sürüm tutuyorsa uygulanır."""
    simdi = time.time()
    if (o['tur'] != 'bot' or o['bitti'] or o['beyaz_sirasi'] or o['istek']
            or simdi - o['son_hamle_zamani'] < BOT_BEKLEME or simdi - o['bot_basladi'] < 15):
        return

    def sahiplen(oda):
        if oda is None or oda['bitti'] or oda['beyaz_sirasi'] or time.time() - oda['bot_basladi'] < 15:
            return None, False
        oda['bot_basladi'] = time.time()
        return (K.durum_kopyala(oda['d']), oyun.anlik_sureler(oda)['siyah'], oda['bot']), True

    bilgi, sahip_surum = depo.oda_guncelle(oid, sahiplen)
    if not bilgi:
        return
    durum, kalan, zorluk = bilgi
    hamle = bot.hamle_sec(durum, False, zorluk, kalan)

    def uygula(oda):
        if oda is None or not hamle:
            return None, False
        oda['bot_basladi'] = 0
        guncel = oda['hamleler'] and not oda['bitti'] and not oda['beyaz_sirasi']
        if guncel and not oyun.sure_kontrol(oda):
            oyun.hamle_yap(oda, *hamle)
        return None, True
    # Bu arada geri alma/yeni oyun olduysa (sürüm değiştiyse) hamleyi uygulama
    depo.oda_guncelle(oid, lambda oda: uygula(oda) if oda and _surum_ayni(oid, sahip_surum) else (None, False))
    mac_kaydet_gerekirse(oid)


def _surum_ayni(oid, surum):
    satir = depo.baglanti().execute("SELECT surum FROM odalar WHERE id = ?", (oid,)).fetchone()
    return satir and satir['surum'] == surum


@app.route('/api/durum')
def api_durum():
    oid, kim = oda_id(), kimlik()
    surum, o = depo.oda_oku(oid)
    if o is None:
        return hata('Oda bulunamadı.', 404, yok=True)
    taraf = oyun.taraf_bul(o, kim)
    if taraf:
        depo.nabiz(oid, taraf)

    simdi = time.time()
    if not o['bitti']:
        # Süre bitti mi / lobi oyununda ilk hamle yapılmadı mı?
        t = oyun.sira_taraf(o)
        sure_bitti = o['basladi'] and oyun.anlik_sureler(o, simdi)[t] <= 0
        ilk_hamle_yok = (o['tur'] == 'lobi' and not o['hamleler']
                         and simdi - o['olusturma'] > ILK_HAMLE_SURESI)
        if sure_bitti or ilk_hamle_yok:
            def fn(oda):
                if oda is None or oda['bitti']:
                    return None, False
                if oyun.sure_kontrol(oda):
                    return None, True
                if oda['tur'] == 'lobi' and not oda['hamleler'] and time.time() - oda['olusturma'] > ILK_HAMLE_SURESI:
                    oyun.oyunu_bitir(oda, '*', 'iptal', 'İlk hamle yapılmadığı için oyun iptal edildi.')
                    return None, True
                return None, False
            depo.oda_guncelle(oid, fn)
            mac_kaydet_gerekirse(oid)
        elif o['tur'] == 'bot':
            _bot_oynat(oid, o, surum)
        surum, o = depo.oda_oku(oid)

    try:
        istemci_surum = int(request.args.get('v', -1))
    except ValueError:
        istemci_surum = -1
    baglantilar = depo.baglanti_durumu(oid)
    if istemci_surum == surum:
        # Değişiklik yok: sadece saat ve bağlantı bilgisi
        sureler = oyun.anlik_sureler(o)
        return tamam(ayni=True, surum=surum, taraf=taraf or 'izleyici',
                     sure={t: round(sureler[t], 1) for t in oyun.TARAFLAR},
                     bagli={t: (t == 'siyah' and o['tur'] == 'bot') or bool(baglantilar.get(t)) for t in oyun.TARAFLAR})
    return tamam(taraf=taraf or 'izleyici', oda=oyun.gorunum(o, surum, baglantilar))


# =====================================================================
# Oyun içi işlemler
# =====================================================================
def oyuncu_islemi(fn_icerik):
    """İsteği gönderen sekmenin odadaki tarafını bulup fn_icerik(oda, taraf) -> (sonuc, degisti) çalıştırır."""
    oid, kim = oda_id(), kimlik()

    def fn(o):
        if o is None:
            return ('hata', 'Oda bulunamadı.'), False
        taraf = oyun.taraf_bul(o, kim)
        if not taraf:
            return ('hata', 'Bu oyunda oyuncu değilsin.'), False
        return fn_icerik(o, taraf)

    sonuc, _ = depo.oda_guncelle(oid, fn)
    mac_kaydet_gerekirse(oid)
    if isinstance(sonuc, tuple) and sonuc and sonuc[0] == 'hata':
        return hata(sonuc[1])
    return tamam(**(sonuc or {}))


def _kare(deger):
    try:
        r, c = int(deger[0]), int(deger[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    return (r, c) if 0 <= r < 8 and 0 <= c < 8 else None


def _rakip_hazir(o):
    return all(o['oyuncular'][t]['katildi'] for t in oyun.TARAFLAR)


@app.route('/api/gecerli', methods=['POST'])
def api_gecerli():
    surum, o = depo.oda_oku(oda_id())
    kare = _kare([veri().get('r'), veri().get('c')])
    if o is None or kare is None or o['bitti']:
        return tamam(moves=[])
    taraf = oyun.taraf_bul(o, kimlik())
    if taraf != oyun.sira_taraf(o):
        return tamam(moves=[])
    return tamam(moves=K.gecerli_hamleleri_bul(o['d'], kare[0], kare[1], o['beyaz_sirasi']))


@app.route('/api/hamle', methods=['POST'])
def api_hamle():
    bas, hed = _kare(veri().get('from')), _kare(veri().get('to'))
    terfi = veri().get('promotion')
    if bas is None or hed is None:
        return hata('Geçersiz hamle verisi.')

    def fn(o, taraf):
        if oyun.sure_kontrol(o):
            return ('hata', 'Süre doldu!'), True
        if o['bitti']:
            return ('hata', 'Oyun bitti.'), False
        if not _rakip_hazir(o):
            return ('hata', 'Rakip henüz katılmadı.'), False
        if taraf != oyun.sira_taraf(o):
            return ('hata', 'Sıra sende değil.'), False
        if not oyun.hamle_gecerli_mi(o, *bas, *hed):
            return ('hata', 'Kural dışı hamle.'), False
        san = oyun.hamle_yap(o, *bas, *hed, terfi)
        return {'san': san}, True
    return oyuncu_islemi(fn)


@app.route('/api/teslim', methods=['POST'])
def api_teslim():
    def fn(o, taraf):
        if o['bitti']:
            return ('hata', 'Oyun zaten bitti.'), False
        if not o['hamleler'] and o['tur'] != 'bot':
            oyun.oyunu_bitir(o, '*', 'iptal', 'Oyun başlamadan iptal edildi.')
        else:
            oyun.teslim_ol(o, taraf)
        return None, True
    return oyuncu_islemi(fn)


@app.route('/api/istek', methods=['POST'])
def api_istek():
    tip = veri().get('tip')
    if tip not in ('geri', 'yeni', 'berabere'):
        return hata('Geçersiz istek.')

    def fn(o, taraf):
        if o['istek']:
            return ('hata', 'Zaten bekleyen bir istek var.'), False
        if tip == 'geri':
            if o['puanli']:
                return ('hata', 'Puanlı oyunlarda hamle geri alınamaz.'), False
            adet = oyun.geri_alma_adedi(o, taraf)
            if not adet:
                return ('hata', 'Geri alınacak hamle yok.'), False
            if o['tur'] == 'bot':
                oyun.geri_al(o, adet)
                return {'tamamlandi': True}, True
        elif tip == 'berabere':
            if o['bitti'] or not o['hamleler']:
                return ('hata', 'Şu an beraberlik teklif edilemez.'), False
            if o['tur'] == 'bot':
                if bot.beraberlik_kabul_eder_mi(o['d'], False):
                    oyun.berabere_bitir(o)
                    return {'tamamlandi': True}, True
                return {'reddedildi': True, 'mesaj': 'Bot beraberliği reddetti 🤖'}, False
        elif tip == 'yeni':
            # Bot oyunu, biten oyun ya da hiç hamle yoksa onay gerekmez
            if o['tur'] == 'bot' or not o['hamleler']:
                if o['tur'] == 'bot':
                    zorluk = veri().get('zorluk')
                    if zorluk in bot.SEVIYELER:
                        o['bot'] = zorluk
                _yeniden_baslat(o)
                return {'tamamlandi': True}, True
            if not o['bitti']:
                return ('hata', 'Oyun sürerken yeni oyun başlatılamaz. Önce teslim ol ya da beraberlik teklif et.'), False
        o['istek'] = {'tip': tip, 'taraf': taraf, 'no': len(o['hamleler'])}
        return None, True
    return oyuncu_islemi(fn)


def _yeniden_baslat(o):
    """Rövanş: tahta sıfırlanır; insanlar arası oyunlarda renkler değişir."""
    if o['tur'] != 'bot' and o['hamleler']:
        o['oyuncular']['beyaz'], o['oyuncular']['siyah'] = o['oyuncular']['siyah'], o['oyuncular']['beyaz']
    oyun.oyunu_baslat(o)
    o['olusturma'] = time.time()


@app.route('/api/cevap', methods=['POST'])
def api_cevap():
    kabul = bool(veri().get('kabul'))

    def fn(o, taraf):
        istek = o['istek']
        if not istek:
            return None, False
        if istek['taraf'] == taraf:
            if not kabul:          # isteyen geri çekti
                o['istek'] = None
                return None, True
            return None, False
        o['istek'] = None
        if kabul and istek['no'] == len(o['hamleler']):
            if istek['tip'] == 'geri':
                adet = oyun.geri_alma_adedi(o, istek['taraf'])
                if adet:
                    oyun.geri_al(o, adet)
            elif istek['tip'] == 'berabere' and not o['bitti']:
                oyun.berabere_bitir(o)
            elif istek['tip'] == 'yeni':
                _yeniden_baslat(o)
        return None, True
    return oyuncu_islemi(fn)


@app.route('/api/sure', methods=['POST'])
def api_sure():
    sure = veri().get('sure')
    if sure not in oyun.SURE_SECENEKLERI:
        return hata('Geçersiz süre.')

    def fn(o, taraf):
        if o['tur'] == 'lobi':
            return ('hata', 'Lobi oyunlarında süre değiştirilemez.'), False
        if o['hamleler'] and not o['bitti']:
            return ('hata', 'Oyun başladıktan sonra süre değiştirilemez.'), False
        o['sure_ayari'] = sure
        oyun.oyunu_baslat(o)
        return None, True
    return oyuncu_islemi(fn)


@app.route('/api/sohbet', methods=['POST'])
def api_sohbet():
    metin = str(veri().get('metin') or '').strip()[:200]
    if not metin:
        return hata('Boş mesaj.')

    def fn(o, taraf):
        if o['tur'] == 'bot':
            return ('hata', 'Bot ile sohbet yok.'), False
        oyun.sohbet_ekle(o, taraf, metin)
        return None, True
    return oyuncu_islemi(fn)


@app.route('/api/ayril', methods=['POST'])
def api_ayril():
    surum, o = depo.oda_oku(oda_id())
    taraf = oyun.taraf_bul(o, kimlik()) if o else None
    if taraf:
        depo.ayril(oda_id(), taraf)
    return tamam()


# =====================================================================
# Lobi: rakip bulma
# =====================================================================
def _eslestir(con, ben, rakip_kaydi):
    """İki oyuncuyu yeni bir lobi odasına koyar. ben: {kimlik, ad, kullanici}, rakip_kaydi: kuyruk satırı."""
    o = oyun.yeni_oda('lobi', rakip_kaydi['sure_ayari'])
    rakip_k = depo.kullanici_id_ile(rakip_kaydi['kullanici_id']) if rakip_kaydi['kullanici_id'] else None
    benim_taraf = random.choice(oyun.TARAFLAR)
    _oyuncuyu_yerlestir(o, benim_taraf, ben['kimlik'], ben['kullanici'], ben['ad'])
    _oyuncuyu_yerlestir(o, oyun.rakip(benim_taraf), rakip_kaydi['kimlik'], rakip_k, rakip_kaydi['ad'])
    o['puanli'] = bool(ben['kullanici'] and rakip_k)
    oid = oyun.yeni_oda_id()
    o['_id'] = oid
    depo.oda_ekle(con, oid, o)
    con.execute("UPDATE kuyruk SET oda = ?, taraf = ? WHERE kimlik = ?", (oid, oyun.rakip(benim_taraf), rakip_kaydi['kimlik']))
    con.execute("DELETE FROM kuyruk WHERE kimlik = ?", (ben['kimlik'],))
    return oid, benim_taraf


def _ben():
    k = aktif_kullanici()
    return {'kimlik': kimlik(), 'kullanici': k, 'ad': k['ad'] if k else misafir_adi()}


@app.route('/api/lobi/ara', methods=['POST'])
def api_lobi_ara():
    ben = _ben()
    sure = veri().get('sure')
    if not ben['kimlik'] or sure not in oyun.SURE_SECENEKLERI:
        return hata('Geçersiz istek.')
    simdi = time.time()
    with depo.islem() as con:
        con.execute("DELETE FROM kuyruk WHERE kimlik = ?", (ben['kimlik'],))
        kid = ben['kullanici']['id'] if ben['kullanici'] else None
        aday = con.execute(
            "SELECT * FROM kuyruk WHERE oda IS NULL AND sure_ayari = ? AND son > ? AND kimlik != ? "
            "AND (kullanici_id IS NULL OR ? IS NULL OR kullanici_id != ?) ORDER BY zaman LIMIT 1",
            (sure, simdi - depo.KUYRUK_SURESI, ben['kimlik'], kid, kid)).fetchone()
        if aday:
            oid, taraf = _eslestir(con, ben, dict(aday))
            return tamam(eslesme={'oda': oid, 'taraf': taraf})
        con.execute("INSERT INTO kuyruk (kimlik, ad, kullanici_id, elo, sure_ayari, zaman, son) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (ben['kimlik'], ben['ad'], kid, ben['kullanici']['elo'] if ben['kullanici'] else None, sure, simdi, simdi))
    return tamam(bekliyor=True)


@app.route('/api/lobi/kabul', methods=['POST'])
def api_lobi_kabul():
    """Bekleyenler listesinden belirli bir oyuncuya meydan oku."""
    ben = _ben()
    try:
        no = int(veri().get('no'))
    except (TypeError, ValueError):
        return hata('Geçersiz istek.')
    with depo.islem() as con:
        aday = con.execute("SELECT rowid AS no, * FROM kuyruk WHERE rowid = ? AND oda IS NULL AND son > ?",
                           (no, time.time() - depo.KUYRUK_SURESI)).fetchone()
        if not aday or aday['kimlik'] == ben['kimlik']:
            return hata('Bu oyuncu artık beklemiyor.')
        if ben['kullanici'] and aday['kullanici_id'] == ben['kullanici']['id']:
            return hata('Kendinle oynayamazsın 🙂')
        oid, taraf = _eslestir(con, ben, dict(aday))
    return tamam(eslesme={'oda': oid, 'taraf': taraf})


@app.route('/api/lobi/iptal', methods=['POST'])
def api_lobi_iptal():
    depo.baglanti().execute("DELETE FROM kuyruk WHERE kimlik = ? AND oda IS NULL", (kimlik(),))
    return tamam()


@app.route('/api/lobi')
def api_lobi():
    kim = kimlik()
    con = depo.baglanti()
    eslesme = None
    benim = con.execute("SELECT * FROM kuyruk WHERE kimlik = ?", (kim,)).fetchone() if kim else None
    if benim:
        if benim['oda']:
            eslesme = {'oda': benim['oda'], 'taraf': benim['taraf']}
            con.execute("DELETE FROM kuyruk WHERE kimlik = ?", (kim,))
        else:
            con.execute("UPDATE kuyruk SET son = ? WHERE kimlik = ?", (time.time(), kim))
    bekleyenler = [dict(r) for r in con.execute(
        "SELECT rowid AS no, ad, elo, sure_ayari, kimlik = ? AS ben FROM kuyruk WHERE oda IS NULL AND son > ? ORDER BY zaman",
        (kim, time.time() - depo.KUYRUK_SURESI))]
    return tamam(eslesme=eslesme, araniyor=bool(benim and not benim['oda']),
                 bekleyenler=bekleyenler, canli=depo.canli_oyunlar())


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
