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
        self.assertTrue(a.post('/api/kayit', {'ad': 'Oyuncu1', 'sifre': 'gizli123'})['success'])
        self.assertTrue(b.post('/api/kayit', {'ad': 'Oyuncu2', 'sifre': 'gizli123'})['success'])
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
        c.post('/api/kayit', {'ad': 'Oyuncu3', 'sifre': 'gizli123'})
        self.assertFalse(Istemci('H').post('/api/giris', {'ad': 'Oyuncu3', 'sifre': 'yanlis'})['success'])
        self.assertTrue(Istemci('H').post('/api/giris', {'ad': 'oyuncu3', 'sifre': 'gizli123'})['success'])


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


if __name__ == '__main__':
    unittest.main()
