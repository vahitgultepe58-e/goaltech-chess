"""Kural motoru testleri: perft (bilinen pozisyonlarda yasal hamle sayıları) ve SAN notasyonu."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import kurallar as K  # noqa: E402


def fen_yukle(fen):
    yerlesim, sira, rok, ep = fen.split()[:4]
    tahta = []
    for satir in yerlesim.split('/'):
        s = []
        for ch in satir:
            s += [' '] * int(ch) if ch.isdigit() else [ch]
        tahta.append(s)
    d = {'tahta': tahta, 'gecerken': None if ep == '-' else [8 - int(ep[1]), 'abcdefgh'.index(ep[0])]}
    d['b_sah'] = 'K' not in rok and 'Q' not in rok
    d['b_k_sag'], d['b_k_sol'] = 'K' not in rok, 'Q' not in rok
    d['s_sah'] = 'k' not in rok and 'q' not in rok
    d['s_k_sag'], d['s_k_sol'] = 'k' not in rok, 'q' not in rok
    return d, sira == 'w'


def perft(d, beyaz, derinlik):
    hamleler = K.tum_hamleler(d, beyaz)
    toplam = 0
    for m in hamleler:
        terfi_mi = d['tahta'][m[0]][m[1]].upper() == 'P' and m[2] in (0, 7)
        for t in (('Q', 'R', 'B', 'N') if terfi_mi else (None,)):
            if derinlik == 1:
                toplam += 1
                continue
            k = K.durum_kopyala(d)
            K.hamle_uygula(k, *m, t)
            toplam += perft(k, not beyaz, derinlik - 1)
    return toplam


class PerftTesti(unittest.TestCase):
    """Değerler: https://www.chessprogramming.org/Perft_Results"""
    POZISYONLAR = [
        ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -", [20, 400, 8902]),
        ("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq -", [48, 2039]),
        ("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - -", [14, 191, 2812]),
        ("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq -", [6, 264, 9467]),
        ("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ -", [44, 1486]),
    ]

    def test_perft(self):
        for fen, beklenen in self.POZISYONLAR:
            d, beyaz = fen_yukle(fen)
            for derinlik, sayi in enumerate(beklenen, 1):
                with self.subTest(fen=fen, derinlik=derinlik):
                    self.assertEqual(perft(d, beyaz, derinlik), sayi)


class NotasyonTesti(unittest.TestCase):
    def oyna(self, hamleler):
        d, sonuc = K.baslangic_durumu(), []
        for u in hamleler.split():
            b_sat, b_sut, h_sat, h_sut, t = K.uci_coz(u)
            sonuc.append(K.san_uret(d, b_sat, b_sut, h_sat, h_sut, t))
            K.hamle_uygula(d, b_sat, b_sut, h_sat, h_sut, t)
        return ' '.join(sonuc)

    def test_san(self):
        self.assertEqual(self.oyna('e2e4 e7e5 g1f3 b8c6 f1b5 a7a6 b5c6 d7c6 e1g1'), 'e4 e5 Nf3 Nc6 Bb5 a6 Bxc6 dxc6 O-O')
        self.assertEqual(self.oyna('f2f3 e7e5 g2g4 d8h4'), 'f3 e5 g4 Qh4#')
        self.assertEqual(self.oyna('g1f3 g8f6 b1c3 b8c6 c3e4 c6e5 e4g5'), 'Nf3 Nf6 Nc3 Nc6 Ne4 Ne5 Neg5')

    def test_konum_anahtari_alinamayan_gecerken(self):
        d = K.baslangic_durumu()
        K.hamle_uygula(d, 6, 4, 4, 4)   # e4: geçerken karesi var ama alacak siyah piyon yok
        self.assertTrue(K.konum_anahtari(d, False).endswith('_'))

    def test_yetersiz_materyal(self):
        bos = [[' '] * 8 for _ in range(8)]
        bos[0][0], bos[7][7], bos[3][3] = 'k', 'K', 'N'
        self.assertTrue(K.yetersiz_materyal_mi(bos))
        bos[3][4] = 'P'
        self.assertFalse(K.yetersiz_materyal_mi(bos))


if __name__ == '__main__':
    unittest.main()
