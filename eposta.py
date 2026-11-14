"""E-posta gönderimi (SMTP).

Ayarlar `eposta_ayar.json` dosyasından (uygulama klasöründe, gizli tutulur) ya da ortam değişkenlerinden okunur:
    GOALTECH_SMTP_SUNUCU, GOALTECH_SMTP_PORT, GOALTECH_SMTP_KULLANICI, GOALTECH_SMTP_SIFRE, GOALTECH_SMTP_GONDEREN
Gmail için: sunucu smtp.gmail.com, port 587, şifre olarak Google hesabında oluşturulan "Uygulama şifresi".
"""
import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

KLASOR = os.path.dirname(os.path.abspath(__file__))
AYAR_DOSYASI = os.path.join(KLASOR, 'eposta_ayar.json')


def ayarlar():
    a = {}
    try:
        with open(AYAR_DOSYASI, encoding='utf-8') as f:
            a = json.load(f)
    except (FileNotFoundError, ValueError):
        pass
    for anahtar in ('sunucu', 'port', 'kullanici', 'sifre', 'gonderen'):
        deger = os.environ.get('GOALTECH_SMTP_' + anahtar.upper())
        if deger:
            a[anahtar] = deger
    return a


def hazir_mi():
    a = ayarlar()
    return bool(a.get('sunucu') and a.get('kullanici') and a.get('sifre')) and 'BURAYA' not in str(a.get('sifre'))


def gonder(alici, konu, metin, baglanti=None, dugme=None):
    """Düz metin + basit HTML e-posta gönderir. Başarılıysa True."""
    a = ayarlar()
    if not hazir_mi():
        return False
    mesaj = EmailMessage()
    mesaj['Subject'] = konu
    mesaj['From'] = formataddr((a.get('gonderen') or 'Goaltech Chess', a['kullanici']))
    mesaj['To'] = alici
    duz = metin + (f"\n\n{baglanti}\n" if baglanti else '') + "\n— Goaltech Chess"
    mesaj.set_content(duz)
    if baglanti:
        paragraflar = ''.join(f'<p style="margin:0 0 12px">{satir}</p>' for satir in metin.split('\n') if satir.strip())
        mesaj.add_alternative(f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;color:#222">
<h2 style="color:#5d8c2e">Goaltech Chess</h2>{paragraflar}
<p style="margin:20px 0"><a href="{baglanti}" style="background:#81b64c;color:#fff;padding:12px 20px;border-radius:8px;text-decoration:none;font-weight:bold">{dugme or 'Devam et'}</a></p>
<p style="color:#888;font-size:12px">Düğme çalışmazsa bu adresi tarayıcına yapıştır:<br>{baglanti}</p></div>""", subtype='html')
    try:
        with smtplib.SMTP(a['sunucu'], int(a.get('port') or 587), timeout=20) as s:
            s.starttls(context=ssl.create_default_context())
            s.login(a['kullanici'], a['sifre'])
            s.send_message(mesaj)
        return True
    except (smtplib.SMTPException, OSError) as e:
        print('E-POSTA HATASI:', e)
        return False
