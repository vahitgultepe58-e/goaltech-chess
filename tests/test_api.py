"""Sunucu akış testleri: odalar, lobi, hesaplar, Elo, bot, süre."""
import os
import sys
import tempfile
import time
import unittest

KOK = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, KOK)
os.environ['GOALTECH_DB'] = os.path.join(tempfile.mkdtemp(), 'test.db')
os.environ['GOALTECH_SECRET'] = 'test'
import app as A  # noqa: E402
import depo  # noqa: E402

A.BOT_BEKLEME = 0


def kare(s):
    return [8 - int(s[1]), 'abcdefgh'.index(s[0])]


class Istemci:
    def __init__(self, kimlik):
        self.c = A.app.test_client()
        self.id = kimlik

    def post(self, yol, govde=None, oda=None):
        ek = f"{'&' if '?' in yol else '?'}id={self.id}" + (f"&oda={oda}" if oda else '')
        return self.c.post(yol + ek, json=govde or {}).get_json()

    def get(self, yol, oda=None):
        ek = f"{'&' if '?' in yol else '?'}id={self.id}" + (f"&oda={oda}" if oda else '')
        return self.c.get(yol + ek).get_json()

    def hamle(self, oda, a, b):
        return self.post('/api/hamle', {'from': kare(a), 'to': kare(b)}, oda)

    def durum(self, oda):
        return self.get('/api/durum', oda)['oda']


class ArkadasOdasi(unittest.TestCase):
    def setUp(self):
        self.w, self.b, self.x = Istemci('W'), Istemci('B'), Istemci('X')
        self.oda = self.w.post('/api/oda', {'tur': 'arkadas', 'ad': 'Ali', 'sure': '3+2'})['oda']
        self.assertEqual(self.w.post('/api/katil', {}, self.oda)['taraf'], 'beyaz')
        self.assertEqual(self.b.post('/api/katil', {'ad': 'Veli'}, self.oda)['taraf'], 'siyah')

    def test_izleyici_oynayamaz(self):
        self.assertEqual(self.x.post('/api/katil', {}, self.oda)['taraf'], 'izleyici')
        self.assertFalse(self.x.hamle(self.oda, 'e2', 'e4')['success'])

    def test_sira_ve_kural(self):
        self.assertFalse(self.b.hamle(self.oda, 'e7', 'e5')['success'])
        self.assertFalse(self.w.hamle(self.oda, 'e2', 'e5')['success'])
        self.assertTrue(self.w.hamle(self.oda, 'e2', 'e4')['success'])

    def test_geri_al_onayli(self):
        for c, a, b in [(self.w, 'e2', 'e4'), (self.b, 'e7', 'e5')]:
            c.hamle(self.oda, a, b)
        self.w.post('/api/istek', {'tip': 'geri'}, self.oda)
        self.assertEqual(len(self.w.durum(self.oda)['hamleler']), 2)       # onay bekleniyor
        self.b.post('/api/cevap', {'kabul': True}, self.oda)
        self.assertEqual(self.w.durum(self.oda)['hamleler'], [])           # beyazın hamlesi geri alındı

    def test_beraberlik_ve_rovans(self):
        self.w.hamle(self.oda, 'e2', 'e4')
        self.b.post('/api/istek', {'tip': 'berabere'}, self.oda)
        self.w.post('/api/cevap', {'kabul': True}, self.oda)
        o = self.w.durum(self.oda)
        self.assertEqual((o['bitti'], o['sonuc']), (True, '1/2-1/2'))
        self.assertIsNotNone(o['mac_id'])
        self.w.post('/api/istek', {'tip': 'yeni'}, self.oda)
        self.b.post('/api/cevap', {'kabul': True}, self.oda)
        o = self.w.durum(self.oda)
        self.assertEqual(o['oyuncular']['beyaz']['ad'], 'Veli')            # renkler değişti

    def test_sure_ve_artis(self):
        self.w.hamle(self.oda, 'e2', 'e4')
        self.b.hamle(self.oda, 'e7', 'e5')
        self.assertEqual(self.w.durum(self.oda)['sure']['siyah'], 182.0)

        def eskit(o):
            o['son_zaman'] -= 500
            return None, True
        depo.oda_guncelle(self.oda, eskit)
        o = self.w.durum(self.oda)
        self.assertEqual(o['sonuc'], '0-1')
        self.assertEqual(o['sebep'], 'sure')

    def test_sohbet(self):
        self.b.post('/api/sohbet', {'metin': 'selam'}, self.oda)
        self.assertEqual(self.w.durum(self.oda)['sohbet'][-1]['metin'], 'selam')


class LobiVeElo(unittest.TestCase):
    def test_puanli_mac(self):
        a, b = Istemci('LA'), Istemci('LB')
        self.assertTrue(a.post('/api/kayit', {'ad': 'Oyuncu1', 'sifre': 'gizliSifre123'})['success'])
        self.assertTrue(b.post('/api/kayit', {'ad': 'Oyuncu2', 'sifre': 'gizliSifre123'})['success'])
        self.assertTrue(a.post('/api/lobi/ara', {'sure': '5+0'})['bekliyor'])
        e = b.post('/api/lobi/ara', {'sure': '5+0'})['eslesme']
        oda = e['oda']
        self.assertEqual(a.get('/api/lobi')['eslesme']['oda'], oda)
        beyaz, siyah = (a, b) if e['taraf'] == 'siyah' else (b, a)
        self.assertFalse(beyaz.post('/api/istek', {'tip': 'geri'}, oda)['success'])  # puanlıda geri alma yok
        for c, x, y in [(beyaz, 'f2', 'f3'), (siyah, 'e7', 'e5'), (beyaz, 'g2', 'g4'), (siyah, 'd8', 'h4')]:
            self.assertTrue(c.hamle(oda, x, y)['success'])
        o = a.durum(oda)
        self.assertEqual((o['sonuc'], o['sebep']), ('0-1', 'mat'))
        self.assertEqual(o['elo_degisim'], {'beyaz': -20, 'siyah': 20})
        liste = {k['ad']: k['elo'] for k in a.get('/api/liderlik')['liste']}
        self.assertEqual(sorted(liste.values()), [1180, 1220])
        tekrar = a.get(f"/api/mac/{o['mac_id']}")
        self.assertEqual(tekrar['san'], ['f3', 'e5', 'g4', 'Qh4#'])

    def test_hatali_giris(self):
        c = Istemci('G')
        c.post('/api/kayit', {'ad': 'Oyuncu3', 'sifre': 'gizliSifre123'})
        self.assertFalse(Istemci('H').post('/api/giris', {'ad': 'Oyuncu3', 'sifre': 'yanlis'})['success'])
        self.assertTrue(Istemci('H').post('/api/giris', {'ad': 'oyuncu3', 'sifre': 'gizliSifre123'})['success'])


class BotOyunu(unittest.TestCase):
    def test_bot_cevap_verir(self):
        c = Istemci('BOT1')
        oda = c.post('/api/oda', {'tur': 'bot', 'zorluk': 'orta'})['oda']
        self.assertTrue(c.hamle(oda, 'e2', 'e4')['success'])
        for _ in range(50):
            o = c.durum(oda)
            if len(o['hamleler']) == 2:
                break
            time.sleep(0.1)
        self.assertEqual(len(o['hamleler']), 2)
        self.assertTrue(c.post('/api/istek', {'tip': 'geri'}, oda)['tamamlandi'])
        self.assertEqual(c.durum(oda)['hamleler'], [])


class AvatarVeHiz(unittest.TestCase):
    def test_avatar(self):
        u = Istemci('AV1')
        r = u.post('/api/kayit', {'ad': 'Hayvansever', 'sifre': 'gizliSifre123', 'avatar': '🦊'})
        self.assertEqual(r['kullanici']['avatar'], '🦊')
        self.assertFalse(u.post('/api/avatar', {'avatar': '<b>x</b>'})['success'])      # listede olmayan reddedilir
        self.assertEqual(u.post('/api/avatar', {'avatar': '🐼'})['kullanici']['avatar'], '🐼')
        oda = u.post('/api/oda', {'tur': 'arkadas'})['oda']
        m = Istemci('AV2')
        m.post('/api/katil', {'ad': 'Konuk', 'avatar': '🐸'}, oda)
        o = u.durum(oda)['oyuncular']
        self.assertEqual((o['beyaz']['avatar'], o['siyah']['avatar']), ('🐼', '🐸'))

    def test_durum_yasal_hamleleri_ve_hamle_cevabi(self):
        w, b = Istemci('H1'), Istemci('H2')
        oda = w.post('/api/oda', {'tur': 'arkadas'})['oda']
        b.post('/api/katil', {}, oda)
        o = w.durum(oda)
        self.assertEqual(len(o['yasal']), 10)                                  # 8 piyon + 2 at oynayabilir
        self.assertEqual(sorted(o['yasal']['6,4']), [[4, 4], [5, 4]])
        r = w.hamle(oda, 'e2', 'e4')
        self.assertEqual(r['oda']['hamleler'], ['e4'])                         # yeni durum cevapla birlikte gelir
        self.assertIn('1,4', r['oda']['yasal'])                                # artık siyahın hamleleri


class YonetimPaneli(unittest.TestCase):
    def test_sadece_yonetici_gorur(self):
        os.environ['GOALTECH_YONETICILER'] = 'Patron'
        misafir, uye, patron = Istemci('Y1'), Istemci('Y2'), Istemci('Y3')
        self.assertEqual(misafir.c.get('/api/yonetim').status_code, 401)
        uye.post('/api/kayit', {'ad': 'SiradanUye', 'sifre': 'gizliSifre123'})
        self.assertEqual(uye.c.get('/api/yonetim').status_code, 403)
        r = patron.post('/api/kayit', {'ad': 'Patron', 'sifre': 'gizliSifre123'})
        self.assertTrue(r['kullanici']['yonetici'])
        Istemci('Y4').post('/api/giris', {'ad': 'Patron', 'sifre': 'yanlis'})
        misafir.c.get('/api/ben?z=ziyaretci1', headers={'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Mobile Safari/604.1'})
        misafir.post('/api/oda', {'tur': 'bot', 'ad': 'Konuk', 'sure': '3+2'})
        p = patron.get('/api/yonetim')
        turler = [o['tur'] for o in p['olaylar']]
        for t in ('kayit', 'giris_hatali', 'ziyaret', 'oyun_basladi'):
            self.assertIn(t, turler)
        ziyaret = next(o for o in p['olaylar'] if o['tur'] == 'ziyaret')
        self.assertEqual(ziyaret['cihaz'], 'Telefon · iOS · Safari')
        bot_oyunu = next(o for o in p['olaylar'] if o['tur'] == 'oyun_basladi')
        self.assertIn('3 dk +2 sn', bot_oyunu['detay'])
        self.assertIn('SiradanUye', [k['ad'] for k in p['kullanicilar']])
        self.assertGreaterEqual(p['istatistik']['uye'], 2)


class SifreVeEposta(unittest.TestCase):
    def setUp(self):
        import eposta
        self.giden = []
        self._eski = (eposta.hazir_mi, eposta.gonder)
        eposta.hazir_mi = lambda: True
        eposta.gonder = lambda alici, konu, metin, baglanti=None, dugme=None: self.giden.append((alici, baglanti)) or True

    def tearDown(self):
        import eposta
        eposta.hazir_mi, eposta.gonder = self._eski

    def test_zayif_sifre_reddedilir(self):
        c = Istemci('S0')
        self.assertIn('8 karakter', c.post('/api/kayit', {'ad': 'Zayif', 'sifre': 'kisa1'})['error'])
        self.assertIn('kullanıcı adını', c.post('/api/kayit', {'ad': 'Zayif', 'sifre': 'zayif123456'})['error'])
        self.assertIn('rakam', c.post('/api/kayit', {'ad': 'Zayif', 'sifre': '1234567890'})['error'])

    def test_sifre_degistir_diger_oturumlari_kapatir(self):
        a, b = Istemci('S1'), Istemci('S2')
        a.post('/api/kayit', {'ad': 'Degisken', 'sifre': 'ilkSifre123'})
        b.post('/api/giris', {'ad': 'Degisken', 'sifre': 'ilkSifre123'})
        self.assertEqual(b.get('/api/ben')['kullanici']['ad'], 'Degisken')
        self.assertFalse(a.post('/api/sifre_degistir', {'eski': 'yanlis', 'yeni': 'yeniSifre456'})['success'])
        self.assertTrue(a.post('/api/sifre_degistir', {'eski': 'ilkSifre123', 'yeni': 'yeniSifre456'})['success'])
        self.assertEqual(a.get('/api/ben')['kullanici']['ad'], 'Degisken')     # değiştiren cihaz açık kalır
        self.assertIsNone(b.get('/api/ben')['kullanici'])                       # diğer cihaz çıkış yapar
        self.assertFalse(Istemci('S3').post('/api/giris', {'ad': 'Degisken', 'sifre': 'ilkSifre123'})['success'])
        self.assertTrue(Istemci('S3').post('/api/giris', {'ad': 'Degisken', 'sifre': 'yeniSifre456'})['success'])

    def test_eposta_dogrulama_ve_sifre_sifirlama(self):
        a = Istemci('E1')
        r = a.post('/api/kayit', {'ad': 'Unutkan', 'sifre': 'ilkSifre123', 'eposta': 'unutkan@ornek.com'})
        self.assertTrue(r['dogrulama_gonderildi'])
        self.assertIsNone(a.get('/api/ben')['kullanici']['eposta'])              # henüz doğrulanmadı
        # Doğrulanmamış e-postayla sıfırlama bağlantısı gitmez (ama cevap aynıdır)
        genel = Istemci('E2').post('/api/sifremi_unuttum', {'ad': 'Unutkan'})
        self.assertTrue(genel['success'])
        self.assertEqual(len(self.giden), 1)
        dogrulama = self.giden[-1][1]
        self.assertIn('/dogrula?t=', dogrulama)
        yanit = a.c.get(dogrulama.split('localhost', 1)[1])
        self.assertIn('eposta_dogrulandi', yanit.headers['Location'])
        self.assertEqual(a.get('/api/ben')['kullanici']['eposta'], 'unutkan@ornek.com')
        # Aynı doğrulama bağlantısı ikinci kez çalışmaz
        self.assertIn('dogrulama_gecersiz', a.c.get(dogrulama.split('localhost', 1)[1]).headers['Location'])
        # Var olmayan kullanıcı için de aynı cevap
        self.assertEqual(Istemci('E3').post('/api/sifremi_unuttum', {'ad': 'BoyleBiriYok'})['mesaj'], genel['mesaj'])
        # Şifremi unuttum: e-postayla da çalışır
        self.assertTrue(Istemci('E4').post('/api/sifremi_unuttum', {'ad': 'UNUTKAN@ornek.com'})['success'])
        alici, link = self.giden[-1]
        self.assertEqual(alici, 'unutkan@ornek.com')
        jeton = link.split('sifirla=')[1]
        y = Istemci('E5')
        self.assertTrue(y.post('/api/sifre_sifirla', {'jeton': jeton, 'kontrol': True})['gecerli'])
        self.assertFalse(y.post('/api/sifre_sifirla', {'jeton': jeton, 'yeni': 'kisa'})['success'])   # zayıf, jeton harcanmaz
        r = y.post('/api/sifre_sifirla', {'jeton': jeton, 'yeni': 'yepyeniSifre789'})
        self.assertTrue(r['success'])
        self.assertEqual(y.get('/api/ben')['kullanici']['ad'], 'Unutkan')
        self.assertFalse(Istemci('E6').post('/api/sifre_sifirla', {'jeton': jeton, 'yeni': 'baskaSifre789'})['success'])
        self.assertIsNone(a.get('/api/ben')['kullanici'])                        # eski oturum kapandı
        self.assertTrue(Istemci('E7').post('/api/giris', {'ad': 'Unutkan', 'sifre': 'yepyeniSifre789'})['success'])

    def test_yonetici_gecici_sifre(self):
        os.environ['GOALTECH_YONETICILER'] = 'Patron2'
        y, u = Istemci('G1'), Istemci('G2')
        y.post('/api/kayit', {'ad': 'Patron2', 'sifre': 'patronSifre1'})
        u.post('/api/kayit', {'ad': 'Kaybeden', 'sifre': 'eskiSifre123'})
        self.assertEqual(u.c.post('/api/yonetim/gecici_sifre', json={'ad': 'Kaybeden'}).status_code, 403)
        r = y.post('/api/yonetim/gecici_sifre', {'ad': 'Kaybeden'})
        self.assertEqual(len(r['sifre']), 10)
        self.assertIsNone(u.get('/api/ben')['kullanici'])
        self.assertTrue(Istemci('G3').post('/api/giris', {'ad': 'Kaybeden', 'sifre': r['sifre']})['success'])


if __name__ == '__main__':
    unittest.main()
