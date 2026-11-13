"""SQLite veri katmanı: odalar, bağlantılar, eşleşme kuyruğu, kullanıcılar, maçlar.

Odalar JSON olarak saklanır; her değişiklik `BEGIN IMMEDIATE` ile kilitlenmiş bir işlem içinde yapılır,
böylece sunucu birden fazla işlemle (worker) çalışsa da iki istek aynı odayı aynı anda bozamaz.
"""
import json
import os
import sqlite3
import threading
import time

DB_YOLU = os.environ.get('GOALTECH_DB') or os.path.join(os.path.dirname(os.path.abspath(__file__)), 'goaltech_chess.db')
ODA_OMRU = 24 * 60 * 60          # 24 saat dokunulmayan oda silinir
BAGLANTI_SURESI = 30             # bu kadar saniye ses gelmezse oyuncu "bağlı değil"
KUYRUK_SURESI = 15               # kuyruktaki oyuncu bu kadar saniye sormazsa düşer

_yerel = threading.local()
_onbellek = {}                   # oda_id -> (surum, durum)  (sadece okuma için)
_onbellek_kilit = threading.Lock()
degisim_kancalari = []           # fn(oda_id, surum): oda değişince çağrılır (WebSocket bildirimi için)


def baglanti():
    con = getattr(_yerel, 'con', None)
    if con is None:
        con = sqlite3.connect(DB_YOLU, timeout=20, isolation_level=None, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA busy_timeout = 20000')
        if os.environ.get('GOALTECH_WAL') == '1':
            # WAL hızlıdır ama ağ dosya sistemlerinde (ör. PythonAnywhere) güvenilir değildir; sadece istenirse açılır
            try:
                con.execute('PRAGMA journal_mode = WAL')
            except sqlite3.OperationalError:
                pass
        _yerel.con = con
    return con


def kur():
    con = baglanti()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS odalar (
            id TEXT PRIMARY KEY, surum INTEGER NOT NULL, durum TEXT NOT NULL,
            tur TEXT, bitti INTEGER DEFAULT 0, beyaz_ad TEXT, siyah_ad TEXT,
            beyaz_elo INTEGER, siyah_elo INTEGER, sure_ayari TEXT, hamle_sayisi INTEGER DEFAULT 0,
            guncelleme REAL
        );
        CREATE INDEX IF NOT EXISTS odalar_guncelleme ON odalar(guncelleme);
        CREATE TABLE IF NOT EXISTS baglantilar (
            oda TEXT, taraf TEXT, son REAL, PRIMARY KEY (oda, taraf)
        );
        CREATE TABLE IF NOT EXISTS kuyruk (
            kimlik TEXT PRIMARY KEY, ad TEXT, kullanici_id INTEGER, elo INTEGER,
            sure_ayari TEXT, zaman REAL, son REAL, oda TEXT, taraf TEXT
        );
        CREATE TABLE IF NOT EXISTS kullanicilar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad TEXT UNIQUE COLLATE NOCASE NOT NULL, sifre_hash TEXT NOT NULL,
            elo INTEGER DEFAULT 1200, oyun INTEGER DEFAULT 0, galibiyet INTEGER DEFAULT 0,
            maglubiyet INTEGER DEFAULT 0, beraberlik INTEGER DEFAULT 0, olusturma REAL
        );
        CREATE TABLE IF NOT EXISTS maclar (
            id INTEGER PRIMARY KEY AUTOINCREMENT, oda TEXT,
            beyaz_id INTEGER, siyah_id INTEGER, beyaz_ad TEXT, siyah_ad TEXT,
            sonuc TEXT, sebep TEXT, uci TEXT, san TEXT, sure_ayari TEXT, tur TEXT, bot_zorluk TEXT,
            puanli INTEGER DEFAULT 0, beyaz_elo INTEGER, siyah_elo INTEGER,
            beyaz_degisim INTEGER, siyah_degisim INTEGER, tarih REAL
        );
        CREATE INDEX IF NOT EXISTS maclar_beyaz ON maclar(beyaz_id);
        CREATE INDEX IF NOT EXISTS maclar_siyah ON maclar(siyah_id);
    """)


class _Islem:
    """`with islem() as con:` -> yazma kilidi alınmış işlem; hata olursa geri alınır."""
    def __enter__(self):
        self.con = baglanti()
        self.con.execute('BEGIN IMMEDIATE')
        return self.con

    def __exit__(self, tip, deger, iz):
        self.con.execute('ROLLBACK' if tip else 'COMMIT')
        return False


def islem():
    return _Islem()


# ---------------------------------------------------------------------
# Odalar
# ---------------------------------------------------------------------
def _ozet(o):
    return (o['tur'], int(o['bitti']), o['oyuncular']['beyaz']['ad'], o['oyuncular']['siyah']['ad'],
            o['oyuncular']['beyaz']['elo'], o['oyuncular']['siyah']['elo'], o['sure_ayari'], len(o['hamleler']))


def oda_ekle(con, oda_id, o):
    con.execute("INSERT INTO odalar (id, surum, durum, tur, bitti, beyaz_ad, siyah_ad, beyaz_elo, siyah_elo, "
                "sure_ayari, hamle_sayisi, guncelleme) VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (oda_id, json.dumps(o, ensure_ascii=False), *_ozet(o), time.time()))


def oda_guncelle(oda_id, fn):
    """fn(oda) -> (sonuc, degisti). Oda kilitli işlem içinde okunur, değiştiyse sürümü artırılıp yazılır.
    Oda yoksa fn(None) çağrılır. Dönüş: (sonuc, surum)"""
    with islem() as con:
        satir = con.execute("SELECT surum, durum FROM odalar WHERE id = ?", (oda_id,)).fetchone()
        o = json.loads(satir['durum']) if satir else None
        surum = satir['surum'] if satir else 0
        sonuc, degisti = fn(o)
        if degisti and o is not None:
            surum += 1
            con.execute("UPDATE odalar SET surum = ?, durum = ?, tur = ?, bitti = ?, beyaz_ad = ?, siyah_ad = ?, "
                        "beyaz_elo = ?, siyah_elo = ?, sure_ayari = ?, hamle_sayisi = ?, guncelleme = ? WHERE id = ?",
                        (surum, json.dumps(o, ensure_ascii=False), *_ozet(o), time.time(), oda_id))
    if degisti and o is not None:
        with _onbellek_kilit:
            _onbellek[oda_id] = (surum, o)
        for kanca in degisim_kancalari:
            try:
                kanca(oda_id, surum)
            except Exception:
                pass
    return sonuc, surum


def oda_oku(oda_id):
    """(surum, oda) ya da (0, None). Sürüm değişmediyse JSON tekrar çözülmez."""
    satir = baglanti().execute("SELECT surum FROM odalar WHERE id = ?", (oda_id,)).fetchone()
    if not satir:
        return 0, None
    with _onbellek_kilit:
        kayit = _onbellek.get(oda_id)
    if kayit and kayit[0] == satir['surum']:
        return kayit
    satir = baglanti().execute("SELECT surum, durum FROM odalar WHERE id = ?", (oda_id,)).fetchone()
    if not satir:
        return 0, None
    kayit = (satir['surum'], json.loads(satir['durum']))
    with _onbellek_kilit:
        _onbellek[oda_id] = kayit
    return kayit


def canli_oyunlar(limit=20):
    sinir = time.time() - 15 * 60
    return [dict(r) for r in baglanti().execute(
        "SELECT id, tur, beyaz_ad, siyah_ad, beyaz_elo, siyah_elo, sure_ayari, hamle_sayisi FROM odalar "
        "WHERE bitti = 0 AND tur != 'bot' AND hamle_sayisi > 0 AND guncelleme > ? "
        "ORDER BY guncelleme DESC LIMIT ?", (sinir, limit))]


def temizlik():
    """Eski odaları, bağlantıları ve kuyruk kayıtlarını siler."""
    simdi = time.time()
    with islem() as con:
        eski = [r['id'] for r in con.execute("SELECT id FROM odalar WHERE guncelleme < ?", (simdi - ODA_OMRU,))]
        for oda_id in eski:
            con.execute("DELETE FROM odalar WHERE id = ?", (oda_id,))
            con.execute("DELETE FROM baglantilar WHERE oda = ?", (oda_id,))
        con.execute("DELETE FROM kuyruk WHERE son < ? AND oda IS NULL", (simdi - KUYRUK_SURESI,))
        con.execute("DELETE FROM kuyruk WHERE zaman < ?", (simdi - 3600,))
    with _onbellek_kilit:
        for oda_id in eski:
            _onbellek.pop(oda_id, None)


# ---------------------------------------------------------------------
# Bağlantı (kim şu an sayfada)
# ---------------------------------------------------------------------
def nabiz(oda_id, taraf):
    """Oyuncu sayfada; en fazla 5 saniyede bir yazar."""
    simdi = time.time()
    con = baglanti()
    satir = con.execute("SELECT son FROM baglantilar WHERE oda = ? AND taraf = ?", (oda_id, taraf)).fetchone()
    if satir and simdi - satir['son'] < 5:
        return
    con.execute("INSERT INTO baglantilar (oda, taraf, son) VALUES (?, ?, ?) "
                "ON CONFLICT(oda, taraf) DO UPDATE SET son = excluded.son", (oda_id, taraf, simdi))


def ayril(oda_id, taraf):
    baglanti().execute("UPDATE baglantilar SET son = 0 WHERE oda = ? AND taraf = ?", (oda_id, taraf))


def baglanti_durumu(oda_id):
    sinir = time.time() - BAGLANTI_SURESI
    return {r['taraf']: r['son'] > sinir for r in
            baglanti().execute("SELECT taraf, son FROM baglantilar WHERE oda = ?", (oda_id,))}


# ---------------------------------------------------------------------
# Kullanıcılar
# ---------------------------------------------------------------------
def kullanici_ekle(ad, sifre_hash):
    try:
        with islem() as con:
            cur = con.execute("INSERT INTO kullanicilar (ad, sifre_hash, olusturma) VALUES (?, ?, ?)",
                              (ad, sifre_hash, time.time()))
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def kullanici_ad_ile(ad):
    r = baglanti().execute("SELECT * FROM kullanicilar WHERE ad = ?", (ad,)).fetchone()
    return dict(r) if r else None


def kullanici_id_ile(kid):
    r = baglanti().execute("SELECT * FROM kullanicilar WHERE id = ?", (kid,)).fetchone()
    return dict(r) if r else None


def liderlik(limit=50):
    return [dict(r) for r in baglanti().execute(
        "SELECT ad, elo, oyun, galibiyet, maglubiyet, beraberlik FROM kullanicilar "
        "WHERE oyun > 0 ORDER BY elo DESC, oyun DESC LIMIT ?", (limit,))]


# ---------------------------------------------------------------------
# Maçlar
# ---------------------------------------------------------------------
def mac_ekle(con, alanlar):
    sutunlar = ', '.join(alanlar)
    soru = ', '.join('?' for _ in alanlar)
    return con.execute(f"INSERT INTO maclar ({sutunlar}) VALUES ({soru})", tuple(alanlar.values())).lastrowid


def mac(mid):
    r = baglanti().execute("SELECT * FROM maclar WHERE id = ?", (mid,)).fetchone()
    return dict(r) if r else None


def kullanici_maclari(kid, limit=30):
    return [dict(r) for r in baglanti().execute(
        "SELECT id, beyaz_id, siyah_id, beyaz_ad, siyah_ad, sonuc, sebep, sure_ayari, tur, bot_zorluk, puanli, "
        "beyaz_degisim, siyah_degisim, tarih, length(san) - length(replace(san, ' ', '')) + 1 AS hamle "
        "FROM maclar WHERE beyaz_id = ? OR siyah_id = ? ORDER BY id DESC LIMIT ?", (kid, kid, limit))]
