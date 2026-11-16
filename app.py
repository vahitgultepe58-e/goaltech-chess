"""Goaltech Chess — Flask sunucusu.

Dosyalar:
    kurallar.py  satranç kuralları (perft testli)
    bot.py       yapay zeka rakip
    oyun.py      oda/oyun akışı ve satranç saati
    depo.py      SQLite veri katmanı
    index.html   arayüz
"""
import hashlib
import json
import os
import queue
import random
import re
import secrets
import threading
import time

from flask import Flask, jsonify, redirect, request, send_file, session
from werkzeug.security import check_password_hash, generate_password_hash

try:                                   # WebSocket desteği isteğe bağlı (pip install flask-sock)
    from flask_sock import Sock
except ImportError:
    Sock = None

import bot
import depo
import eposta
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

BOT_BEKLEME = 0            # bot hamlesinden önce beklenecek süre (sn)
AVATARLAR = ('🦁', '🐯', '🦊', '🐺', '🐻', '🐼', '🐨', '🐱', '🐶', '🐰',
             '🦉', '🦅', '🐧', '🐴', '🐘', '🐵', '🐢', '🐬', '🐙', '🐸')
ILK_HAMLE_SURESI = 45      # lobi oyununda ilk hamle bu sürede yapılmazsa oyun iptal
AD_DESENI = re.compile(r'^[A-Za-z0-9_çğıöşüÇĞİÖŞÜ]{3,20}$')
EPOSTA_DESENI = re.compile(r'^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$')
SIFIRLAMA_OMRU = 30 * 60          # şifre sıfırlama bağlantısı 30 dakika geçerli
DOGRULAMA_OMRU = 24 * 60 * 60     # e-posta doğrulama bağlantısı 24 saat geçerli


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
    k = depo.kullanici_id_ile(kid) if kid else None
    # Şifre değişince eski oturumlar geçersiz olur
    if k and session.get('os', 0) != (k.get('oturum_surum') or 0):
        session.clear()
        return None
    return k


def oturum_ac(k):
    session.clear()
    session.permanent = True
    session['kid'] = k['id']
    session['os'] = k.get('oturum_surum') or 0


def sifre_sorunu(ad, sifre):
    """Yeni şifre için kural ihlali varsa açıklamasını döndürür."""
    if len(sifre) < 8:
        return 'Şifre en az 8 karakter olmalı.'
    if len(sifre) > 128:
        return 'Şifre çok uzun.'
    if ad and ad.lower() in sifre.lower():
        return 'Şifre kullanıcı adını içermemeli.'
    if sifre.isdigit():
        return 'Şifre sadece rakamlardan oluşmamalı.'
    return None


_sinirlar = {}
_sinir_kilit = threading.Lock()


def cok_sik_mi(anahtar, adet, sure):
    """Son `sure` saniyede bu anahtarla `adet`ten fazla deneme olduysa True (ve denemeyi sayar)."""
    simdi = time.time()
    with _sinir_kilit:
        liste = [t for t in _sinirlar.get(anahtar, []) if simdi - t < sure]
        if len(liste) >= adet:
            _sinirlar[anahtar] = liste
            return True
        liste.append(simdi)
        _sinirlar[anahtar] = liste
        return False


def jeton_uret():
    jeton = secrets.token_urlsafe(32)
    return jeton, hashlib.sha256(jeton.encode()).hexdigest()


def jeton_ozeti(jeton):
    return hashlib.sha256(str(jeton or '').encode()).hexdigest()


def avatar_al():
    a = veri().get('avatar')
    return a if a in AVATARLAR else None


def misafir_adi():
    ad = (veri().get('ad') or request.args.get('ad') or '').strip()[:20]
    return ad or 'Misafir'


# ---------------------------------------------------------------------
# Yönetim paneli için olay kaydı (IP adresi saklanmaz)
# ---------------------------------------------------------------------
def cihaz_bilgisi():
    """Tarayıcı bilgisinden kaba cihaz özeti: 'Telefon · Android · Chrome'."""
    ua = request.headers.get('User-Agent', '')
    tip = 'Tablet' if ('iPad' in ua or ('Android' in ua and 'Mobile' not in ua)) else \
          'Telefon' if ('Mobi' in ua or 'iPhone' in ua) else 'Bilgisayar'
    sistem = next((ad for anahtar, ad in (('Android', 'Android'), ('iPhone', 'iOS'), ('iPad', 'iOS'),
                                          ('Windows', 'Windows'), ('Mac OS', 'macOS'), ('CrOS', 'ChromeOS'),
                                          ('Linux', 'Linux')) if anahtar in ua), '?')
    tarayici = next((ad for anahtar, ad in (('Edg/', 'Edge'), ('OPR/', 'Opera'), ('SamsungBrowser', 'Samsung'),
                                            ('Firefox/', 'Firefox'), ('Chrome/', 'Chrome'), ('Safari/', 'Safari'))
                     if anahtar in ua), '?')
    return f"{tip} · {sistem} · {tarayici}"


def olay(tur, detay=None, kullanici=None, ad=None, con=None):
    k = kullanici if kullanici is not None else aktif_kullanici()
    depo.olay_ekle(tur, kullanici_id=k['id'] if k else None, ad=(k['ad'] if k else ad),
                   ziyaretci=(request.args.get('z') or '')[:40] or None, cihaz=cihaz_bilgisi(), detay=detay, con=con)


def sure_metni(ayar):
    try:
        dk, ek = (int(x) for x in str(ayar).split('+'))
    except ValueError:
        return str(ayar or '')
    return f"{dk} dk" + (f" +{ek} sn" if ek else '')


def yonetici_mi(k):
    if not k:
        return False
    adlar = {a.strip().lower() for a in os.environ.get('GOALTECH_YONETICILER', '').split(',') if a.strip()}
    try:
        with open(os.path.join(KLASOR, 'yoneticiler.txt'), encoding='utf-8') as f:
            adlar |= {a.strip().lower() for a in f if a.strip() and not a.startswith('#')}
    except FileNotFoundError:
        pass
    return k['ad'].lower() in adlar


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
                               'maglubiyet': k['maglubiyet'], 'beraberlik': k['beraberlik'],
                               'avatar': k.get('avatar')}


def _kendi_ozetim(k):
    """Kullanıcının kendisine gösterilen bilgiler (e-posta dahil)."""
    ozet = _kullanici_ozeti(k)
    if ozet:
        ozet['yonetici'] = yonetici_mi(k)
        ozet['eposta'] = k.get('eposta') if k.get('eposta_dogrulandi') else None
    return ozet


@app.route('/api/ben')
def api_ben():
    k = aktif_kullanici()
    z = (request.args.get('z') or '')[:40]
    if z and depo.ziyaret_yeni_mi(z):
        olay('ziyaret', 'üye' if k else 'misafir', kullanici=k)
    return tamam(kullanici=_kendi_ozetim(k), eposta_hazir=eposta.hazir_mi())


@app.route('/api/kayit', methods=['POST'])
def api_kayit():
    ad = (veri().get('ad') or '').strip()
    sifre = veri().get('sifre') or ''
    if not AD_DESENI.match(ad):
        return hata('Kullanıcı adı 3-20 karakter olmalı; harf, rakam ve _ kullanılabilir.')
    sorun = sifre_sorunu(ad, sifre)
    if sorun:
        return hata(sorun)
    adres = (veri().get('eposta') or '').strip()
    if adres and not EPOSTA_DESENI.match(adres):
        return hata('E-posta adresi geçersiz görünüyor.')
    if cok_sik_mi(('kayit', request.remote_addr), 10, 3600):
        return hata('Çok fazla kayıt denemesi. Biraz sonra tekrar dene.')
    kid = depo.kullanici_ekle(ad, generate_password_hash(sifre))
    if not kid:
        return hata('Bu kullanıcı adı alınmış.')
    depo.avatar_yaz(kid, avatar_al() or random.choice(AVATARLAR))
    yeni = depo.kullanici_id_ile(kid)
    oturum_ac(yeni)
    depo.son_giris_yaz(kid)
    olay('kayit', 'yeni hesap' + (' · e-posta eklendi' if adres else ''), kullanici=yeni)
    gonderildi = _dogrulama_gonder(yeni, adres) if adres else None
    return tamam(kullanici=_kendi_ozetim(yeni), dogrulama_gonderildi=gonderildi)


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
        olay('giris_hatali', 'hesap yok' if not k else 'yanlış şifre', kullanici=False, ad=ad[:20])
        return hata('Kullanıcı adı veya şifre hatalı.')
    oturum_ac(k)
    depo.son_giris_yaz(k['id'])
    olay('giris', None, kullanici=k)
    return tamam(kullanici=_kendi_ozetim(k))


@app.route('/api/cikis', methods=['POST'])
def api_cikis():
    olay('cikis')
    session.clear()
    return tamam()


def _dogrulama_gonder(k, adres):
    jeton, ozet = jeton_uret()
    depo.jeton_ekle(ozet, k['id'], 'eposta', adres, DOGRULAMA_OMRU)
    link = request.host_url.rstrip('/') + '/dogrula?t=' + jeton
    return eposta.gonder(adres, 'Goaltech Chess: e-posta adresini doğrula',
                         f"Merhaba {k['ad']},\nBu e-posta adresini Goaltech Chess hesabına eklemek için aşağıdaki bağlantıya tıkla. "
                         "Bağlantı 24 saat geçerlidir.\nBu isteği sen yapmadıysan bu e-postayı yok sayabilirsin.",
                         baglanti=link, dugme='E-postamı doğrula')


@app.route('/api/avatar', methods=['POST'])
def api_avatar():
    k = aktif_kullanici()
    if not k:
        return hata('Önce giriş yapmalısın.', 401)
    a = avatar_al()
    if not a:
        return hata('Geçersiz avatar.')
    depo.avatar_yaz(k['id'], a)
    return tamam(kullanici=_kendi_ozetim(depo.kullanici_id_ile(k['id'])))


@app.route('/api/sifre_degistir', methods=['POST'])
def api_sifre_degistir():
    k = aktif_kullanici()
    if not k:
        return hata('Önce giriş yapmalısın.', 401)
    eski, yeni = veri().get('eski') or '', veri().get('yeni') or ''
    if cok_sik_mi(('sifre_degistir', k['id']), 8, 600):
        return hata('Çok fazla deneme. 10 dakika sonra tekrar dene.')
    if not check_password_hash(k['sifre_hash'], eski):
        return hata('Mevcut şifren hatalı.')
    sorun = sifre_sorunu(k['ad'], yeni)
    if sorun:
        return hata(sorun)
    depo.sifre_yaz(k['id'], generate_password_hash(yeni))
    oturum_ac(depo.kullanici_id_ile(k['id']))      # bu cihazda açık kal, diğerleri kapanır
    olay('sifre_degisti', 'kullanıcı değiştirdi', kullanici=k)
    return tamam()


@app.route('/api/eposta', methods=['POST'])
def api_eposta():
    k = aktif_kullanici()
    if not k:
        return hata('Önce giriş yapmalısın.', 401)
    adres = (veri().get('eposta') or '').strip()
    if not EPOSTA_DESENI.match(adres):
        return hata('E-posta adresi geçersiz görünüyor.')
    if not eposta.hazir_mi():
        return hata('E-posta gönderimi henüz ayarlanmadı. Site yöneticisine haber ver.')
    if cok_sik_mi(('eposta', k['id']), 5, 3600):
        return hata('Çok fazla deneme. Bir saat sonra tekrar dene.')
    sahibi = depo.kullanici_eposta_ile(adres)
    if sahibi and sahibi['id'] != k['id']:
        return hata('Bu e-posta başka bir hesapta kullanılıyor.')
    if not _dogrulama_gonder(k, adres):
        return hata('E-posta gönderilemedi. Biraz sonra tekrar dene.')
    olay('eposta_gonderildi', 'doğrulama', kullanici=k)
    return tamam()


@app.route('/dogrula')
def dogrula():
    satir = depo.jeton_kullan(jeton_ozeti(request.args.get('t')), 'eposta')
    if not satir:
        return redirect('/?bildirim=dogrulama_gecersiz')
    if not depo.eposta_dogrula(satir['kullanici_id'], satir['eposta']):
        return redirect('/?bildirim=eposta_kullanimda')
    k = depo.kullanici_id_ile(satir['kullanici_id'])
    depo.olay_ekle('eposta_dogrulandi', kullanici_id=k['id'], ad=k['ad'], cihaz=cihaz_bilgisi())
    return redirect('/?bildirim=eposta_dogrulandi')


@app.route('/api/sifremi_unuttum', methods=['POST'])
def api_sifremi_unuttum():
    giris = (veri().get('ad') or '').strip()[:100]
    genel = tamam(mesaj='Bu bilgiyle eşleşen ve e-postası doğrulanmış bir hesap varsa, şifre sıfırlama bağlantısı '
                        'e-postasına gönderildi. Gelen kutunu (ve gereksiz klasörünü) kontrol et.')
    if not giris:
        return hata('Kullanıcı adını ya da e-postanı yaz.')
    if not eposta.hazir_mi():
        return hata('E-posta gönderimi henüz ayarlanmadı. Şifreni sıfırlatmak için site yöneticisine yaz.')
    if cok_sik_mi(('unuttum_ip', request.remote_addr), 10, 3600):
        return hata('Çok fazla istek. Bir saat sonra tekrar dene.')
    k = depo.kullanici_eposta_ile(giris) if '@' in giris else depo.kullanici_ad_ile(giris)
    olay('sifre_sifirlama_istendi', 'hesap bulunamadı' if not k else
         ('e-posta yok' if not k.get('eposta_dogrulandi') else 'bağlantı gönderildi'), kullanici=False,
         ad=(k['ad'] if k else giris[:20]))
    # Hesap olsun olmasın aynı cevap: dışarıdan hangi hesapların var olduğu anlaşılmasın
    if not k or not k.get('eposta_dogrulandi') or cok_sik_mi(('unuttum', k['id']), 3, 3600):
        return genel
    jeton, ozet = jeton_uret()
    depo.jeton_ekle(ozet, k['id'], 'sifre', k['eposta'], SIFIRLAMA_OMRU)
    link = request.host_url.rstrip('/') + '/?sifirla=' + jeton
    eposta.gonder(k['eposta'], 'Goaltech Chess: şifre sıfırlama',
                  f"Merhaba {k['ad']},\nŞifreni sıfırlamak için aşağıdaki bağlantıya tıkla. Bağlantı 30 dakika geçerlidir "
                  "ve sadece bir kez kullanılabilir.\nBu isteği sen yapmadıysan bu e-postayı yok say; şifren değişmez.",
                  baglanti=link, dugme='Yeni şifre belirle')
    return genel


@app.route('/api/sifre_sifirla', methods=['POST'])
def api_sifre_sifirla():
    ozet = jeton_ozeti(veri().get('jeton'))
    if veri().get('kontrol'):
        return tamam(gecerli=depo.jeton_gecerli_mi(ozet, 'sifre'))
    if cok_sik_mi(('sifirla_ip', request.remote_addr), 20, 3600):
        return hata('Çok fazla deneme. Biraz sonra tekrar dene.')
    yeni = veri().get('yeni') or ''
    if not depo.jeton_gecerli_mi(ozet, 'sifre'):
        return hata('Bu bağlantının süresi dolmuş ya da daha önce kullanılmış. Yeniden şifre sıfırlama iste.')
    satir_k = depo.baglanti().execute("SELECT kullanici_id FROM jetonlar WHERE ozet = ?", (ozet,)).fetchone()
    k = depo.kullanici_id_ile(satir_k['kullanici_id']) if satir_k else None
    sorun = sifre_sorunu(k['ad'] if k else '', yeni)
    if sorun:
        return hata(sorun)
    satir = depo.jeton_kullan(ozet, 'sifre')
    if not satir or not k:
        return hata('Bu bağlantının süresi dolmuş ya da daha önce kullanılmış.')
    depo.sifre_yaz(k['id'], generate_password_hash(yeni))
    k = depo.kullanici_id_ile(k['id'])
    oturum_ac(k)
    depo.son_giris_yaz(k['id'])
    olay('sifre_sifirlandi', 'e-posta bağlantısıyla', kullanici=k)
    return tamam(kullanici=_kendi_ozetim(k))


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


def _tur_metni(o):
    if o['tur'] == 'bot':
        return f"Bot ({o['bot']})"
    if o['tur'] == 'lobi':
        return 'Rakip Bul · ' + ('puanlı' if o['puanli'] else 'puansız')
    return 'Arkadaş odası'


def mac_kaydet_gerekirse(oid):
    """Oyun bittiyse ve henüz kaydedilmediyse maçı kaydeder, puanlıysa Elo'ları günceller (tek işlemde)."""
    _, mevcut = depo.oda_oku(oid)      # çoğu hamlede oyun bitmemiştir: yazma kilidi almadan çık
    if not mevcut or not mevcut['bitti'] or mevcut['mac_id'] is not None or mevcut['sonuc'] == '*':
        return

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
        sebepler = {'mat': 'şah mat', 'pat': 'pat', 'teslim': 'teslim', 'sure': 'süre bitti', 'anlasma': 'anlaşma',
                    'tekrar': '3 tekrar', 'elli': '50 hamle', 'materyal': 'yetersiz materyal', 'sure_materyal': 'süre bitti'}
        depo.olay_ekle('oyun_bitti', ad=f"{b['ad']} – {s['ad']}", con=con, detay=(
            f"{o['sonuc']} · {sebepler.get(o['sebep'], o['sebep'])} · {len(o['hamleler'])} yarım hamle · "
            f"{_tur_metni(o)} · {sure_metni(o['sure_ayari'])}"))
        return mid, True
    depo.oda_guncelle(oid, fn)


# =====================================================================
# Oda oluşturma, katılma, durum
# =====================================================================
def _oyuncuyu_yerlestir(o, taraf, kim, kullanici, ad, avatar=None):
    p = o['oyuncular'][taraf]
    p.update({'id': kim, 'katildi': True, 'avatar': kullanici.get('avatar') if kullanici else avatar,
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
    _oyuncuyu_yerlestir(o, 'beyaz', kimlik(), aktif_kullanici(), misafir_adi(), avatar_al())
    oid = oyun.yeni_oda_id()
    o['_id'] = oid
    with depo.islem() as con:
        depo.oda_ekle(con, oid, o)
    olay('oyun_basladi', f"{_tur_metni(o)} · {sure_metni(o['sure_ayari'])} · oda {oid}", ad=o['oyuncular']['beyaz']['ad'])
    return tamam(oda=oid)


@app.route('/api/katil', methods=['POST'])
def api_katil():
    oid, kim = oda_id(), kimlik()
    if not kim:
        return hata('Kimlik eksik.')
    kullanici = aktif_kullanici()
    baglantilar = depo.baglanti_durumu(oid)
    yeni_katilim = {}

    def fn(o):
        if o is None:
            return None, False
        t = oyun.taraf_bul(o, kim)
        if t:
            return t, False
        if veri().get('izle'):            # "İzle" ile gelen kimse oyuncu yerine oturmaz
            return 'izleyici', False
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
                    _oyuncuyu_yerlestir(o, t, kim, kullanici, misafir_adi(), avatar_al())
                    yeni_katilim['evet'] = True
                    return t, True
        return 'izleyici', False

    taraf, _ = depo.oda_guncelle(oid, fn)
    if taraf is None:
        return hata('Oda bulunamadı.', 404, yok=True)
    if taraf != 'izleyici' and yeni_katilim.get('evet'):
        olay('katildi', f"Arkadaş odası · {taraf} · oda {oid}", ad=misafir_adi())
    elif taraf == 'izleyici':
        olay('izledi', f"oda {oid}", ad=misafir_adi())
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


def bot_tetikle(oid):
    """Bot hamlesini istemcinin bir sonraki yoklamasını beklemeden arka planda başlatır.
    Thread desteklenmeyen sunucularda (ör. bazı uWSGI ayarları) yoklama yine botu çalıştırır."""
    def calis():
        time.sleep(BOT_BEKLEME + 0.02)
        try:
            surum, o = depo.oda_oku(oid)
            if o is not None:
                _bot_oynat(oid, o, surum)
        except Exception:
            pass
    try:
        threading.Thread(target=calis, daemon=True).start()
    except RuntimeError:
        pass


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
    # Yeni durumu cevapla birlikte gönder: tarayıcının ayrıca sormasına gerek kalmaz
    surum, o = depo.oda_oku(oid)
    ek = dict(sonuc or {})
    if o is not None:
        ek['oda'] = oyun.gorunum(o, surum, depo.baglanti_durumu(oid))
    return tamam(**ek)


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
        return {'san': san, 'bot': o['tur'] == 'bot' and not o['bitti']}, True
    yanit = oyuncu_islemi(fn)
    govde = yanit[0] if isinstance(yanit, tuple) else yanit   # hata yanıtları (yanıt, kod) şeklinde
    if (govde.get_json() or {}).get('bot'):
        bot_tetikle(oda_id())
    return yanit


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
    _oyuncuyu_yerlestir(o, benim_taraf, ben['kimlik'], ben['kullanici'], ben['ad'], ben['avatar'])
    _oyuncuyu_yerlestir(o, oyun.rakip(benim_taraf), rakip_kaydi['kimlik'], rakip_k, rakip_kaydi['ad'], rakip_kaydi.get('avatar'))
    o['puanli'] = bool(ben['kullanici'] and rakip_k)
    oid = oyun.yeni_oda_id()
    o['_id'] = oid
    depo.oda_ekle(con, oid, o)
    con.execute("UPDATE kuyruk SET oda = ?, taraf = ? WHERE kimlik = ?", (oid, oyun.rakip(benim_taraf), rakip_kaydi['kimlik']))
    con.execute("DELETE FROM kuyruk WHERE kimlik = ?", (ben['kimlik'],))
    olay('oyun_basladi', f"{_tur_metni(o)} · {sure_metni(o['sure_ayari'])} · {o['oyuncular']['beyaz']['ad']} – "
         f"{o['oyuncular']['siyah']['ad']} · oda {oid}", kullanici=ben['kullanici'] or False, ad=ben['ad'], con=con)
    return oid, benim_taraf


def _ben():
    k = aktif_kullanici()
    return {'kimlik': kimlik(), 'kullanici': k, 'ad': k['ad'] if k else misafir_adi(),
            'avatar': k.get('avatar') if k else avatar_al()}


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
        con.execute("INSERT INTO kuyruk (kimlik, ad, kullanici_id, elo, sure_ayari, zaman, son, avatar) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (ben['kimlik'], ben['ad'], kid, ben['kullanici']['elo'] if ben['kullanici'] else None, sure, simdi, simdi, ben['avatar']))
        olay('rakip_aradi', sure_metni(sure), kullanici=ben['kullanici'] or False, ad=ben['ad'], con=con)
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
        "SELECT rowid AS no, ad, avatar, elo, sure_ayari, kimlik = ? AS ben FROM kuyruk WHERE oda IS NULL AND son > ? ORDER BY zaman",
        (kim, time.time() - depo.KUYRUK_SURESI))]
    return tamam(eslesme=eslesme, araniyor=bool(benim and not benim['oda']),
                 bekleyenler=bekleyenler, canli=depo.canli_oyunlar())


# =====================================================================
# Yönetim paneli (sadece yoneticiler.txt'deki hesaplar)
# =====================================================================
@app.route('/yonetim')
def yonetim_sayfasi():
    yanit = send_file(os.path.join(KLASOR, 'yonetim.html'))
    yanit.headers['Cache-Control'] = 'no-cache'
    return yanit


@app.route('/api/yonetim/gecici_sifre', methods=['POST'])
def api_gecici_sifre():
    y = aktif_kullanici()
    if not yonetici_mi(y):
        return hata('Bu işlem sadece yöneticilere açık.', 403)
    k = depo.kullanici_ad_ile((veri().get('ad') or '').strip())
    if not k:
        return hata('Kullanıcı bulunamadı.')
    harfler = 'abcdefghjkmnpqrstuvwxyz23456789'
    gecici = ''.join(secrets.choice(harfler) for _ in range(10))
    depo.sifre_yaz(k['id'], generate_password_hash(gecici))
    olay('gecici_sifre', f"{k['ad']} için geçici şifre üretildi", kullanici=y)
    return tamam(sifre=gecici, ad=k['ad'])


@app.route('/api/yonetim')
def api_yonetim():
    k = aktif_kullanici()
    if not k:
        return hata('Önce giriş yapmalısın.', 401)
    if not yonetici_mi(k):
        return hata('Bu sayfa sadece yöneticilere açık.', 403)
    tur = request.args.get('tur') or None
    ara = (request.args.get('ara') or '').strip()[:40] or None
    con = depo.baglanti()
    sinir = time.time() - depo.BAGLANTI_SURESI
    canli = [dict(r) for r in con.execute(
        "SELECT o.id, o.tur, o.beyaz_ad, o.siyah_ad, o.sure_ayari, o.hamle_sayisi, o.bitti, "
        "(SELECT COUNT(*) FROM baglantilar b WHERE b.oda = o.id AND b.son > ?) AS bagli "
        "FROM odalar o WHERE o.id IN (SELECT oda FROM baglantilar WHERE son > ?) ORDER BY o.guncelleme DESC LIMIT 50",
        (sinir, sinir))]
    return tamam(istatistik=depo.istatistikler(), olaylar=depo.olaylar(400, tur, ara), eposta_hazir=eposta.hazir_mi(),
                 kullanicilar=depo.kullanicilar_listesi(), canli=canli)


# =====================================================================
# Gerçek zamanlı bildirim (WebSocket)
# Oda değiştiğinde bağlı tarayıcılara yeni sürüm numarası gönderilir; tarayıcı da durumu hemen çeker.
# Sunucu WebSocket desteklemiyorsa (ör. PythonAnywhere) tarayıcı otomatik olarak yoklamaya devam eder.
# Not: bildirimler aynı işlem içinde dağıtılır; WebSocket kullanırken tek worker + çok thread ile çalıştırın.
# =====================================================================
_dinleyiciler = {}
_dinleyici_kilit = threading.Lock()


def _oda_degisti(oid, surum):
    with _dinleyici_kilit:
        for q in list(_dinleyiciler.get(oid, ())):
            q.put(surum)


depo.degisim_kancalari.append(_oda_degisti)

if Sock is not None:
    sock = Sock(app)

    @sock.route('/ws')
    def ws(baglanti):
        oid = oda_id()
        q = queue.Queue()
        with _dinleyici_kilit:
            _dinleyiciler.setdefault(oid, set()).add(q)
        try:
            surum, _ = depo.oda_oku(oid)
            baglanti.send(json.dumps({'surum': surum}))
            while True:
                try:
                    surum = q.get(timeout=25)
                    while not q.empty():          # birikmiş bildirimlerden sadece sonuncusu yeter
                        surum = q.get_nowait()
                    baglanti.send(json.dumps({'surum': surum}))
                except queue.Empty:
                    baglanti.send(json.dumps({'ping': 1}))
        finally:
            with _dinleyici_kilit:
                kume = _dinleyiciler.get(oid)
                if kume:
                    kume.discard(q)
                    if not kume:
                        _dinleyiciler.pop(oid, None)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, threaded=True)
