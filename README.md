# Goaltech Chess

Tarayıcıda oynanan çok oyunculu satranç: çevrimiçi eşleşme, puanlı oyunlar (Elo), bilgisayara karşı oyun,
arkadaşla davet linkiyle oyun, izleyici modu, sohbet ve maç tekrarı.

## Özellikler

- **Rakip Bul:** süre seçerek (1+0 … 15+10) çevrimiçi biriyle eşleşme, bekleyen oyuncular listesi, canlı oyunları izleme
- **Hesaplar ve Elo:** kayıt/giriş, iki üye arasındaki lobi oyunları puanlıdır; liderlik tablosu, profil, maç geçmişi
- **Maç tekrarı:** kaydedilen her maç hamle hamle izlenebilir
- **Bot:** Kolay / Orta / Zor (alfa-beta arama), beraberlik teklifine cevap verir
- **Arkadaşla oyun:** davet linki; geri alma ve rövanş rakibin onayıyla
- **Kurallar:** rok, geçerken alma, terfi, şah-mat, pat, 50 hamle, 3 tekrar, yetersiz materyal (perft testli)
- **Satranç saati:** hamle başına ek süre, süre bitimi, puanlı oyunda ilk hamle yapılmazsa iptal
- **Teslim ol, beraberlik teklifi, hamle listesi (SAN), ses, tahtayı çevirme**
- **Gerçek zamanlı:** sunucu destekliyorsa WebSocket, desteklemiyorsa otomatik yoklama

## Dosyalar

| Dosya | İçerik |
|---|---|
| `app.py` | Flask sunucusu ve API |
| `kurallar.py` | Satranç kuralları ve notasyon |
| `bot.py` | Yapay zeka |
| `oyun.py` | Oyun akışı ve satranç saati |
| `depo.py` | SQLite veritabanı |
| `index.html` | Arayüz |
| `tests/` | Otomatik testler |

## Yerelde çalıştırma

```bash
pip install -r requirements.txt
python app.py
```

Tarayıcıda http://localhost:5000 adresini açın.

## Testler

```bash
python -m unittest discover -s tests -v
```

## PythonAnywhere'de yayınlama

1. `app.py`, `kurallar.py`, `bot.py`, `oyun.py`, `depo.py` ve `index.html` dosyalarını **aynı klasöre** yükleyin.
2. **Web** sekmesindeki WSGI dosyasında uygulamanın `from app import app as application` şeklinde yüklendiğinden emin olun.
3. **Reload** düğmesine basın.

PythonAnywhere WebSocket desteklemediği için oyun otomatik olarak yoklama ile çalışır. Veritabanı (`goaltech_chess.db`)
ve oturum anahtarı (`.gizli_anahtar`) ilk çalıştırmada aynı klasörde otomatik oluşturulur.

## WebSocket destekli platformda yayınlama (Render, Railway vb.)

`Procfile` ve `render.yaml` hazırdır. Önemli noktalar:

- **Tek worker, çok thread** ile çalıştırın (`--workers 1 --threads 64`): anlık bildirimler aynı işlem içinde dağıtılır.
- Veritabanını kalıcı bir diske koyun: `GOALTECH_DB=/kalici/disk/goaltech_chess.db`
- `GOALTECH_SECRET` ortam değişkenine uzun, rastgele bir değer verin.

## Ortam değişkenleri

| Değişken | Açıklama |
|---|---|
| `GOALTECH_DB` | Veritabanı dosyasının yolu (varsayılan: uygulama klasörü) |
| `GOALTECH_SECRET` | Oturum çerezlerini imzalayan gizli anahtar (yoksa dosyada üretilir) |
| `GOALTECH_WAL` | `1` ise SQLite WAL modu (yerel diskte daha hızlı; ağ diskinde kullanmayın) |
| `PORT` | Sunucu portu (`python app.py` için) |
