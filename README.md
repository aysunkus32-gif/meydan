# Çatışma Platformu

Üye girişli, tartışmayı ağaç yapısında görselleştiren bir tartışma platformu.

## Kurulum

```bash
# 1. Gerekli paketleri kur
pip install -r requirements.txt

# 2. Uygulamayı başlat
python app.py
```

Tarayıcıda aç: http://localhost:5000

## Özellikler

- **Üye sistemi** — kayıt / giriş / çıkış
- **PC görünümü** — resimdeki gibi yatay açılan ağaç yapısı
- **Mobil görünüm** — geliştirilmiş liste; her cevabın hangi konuya ait olduğu net belli
- **3 cevap türü** — Çünkü (destek), Ama (itiraz), Ancak (koşullu)
- **Silme** — kendi oluşturduklarını silebilirsin
- **SQLite** — veriler `catisma.db` dosyasında saklanır

## Notlar

- `app.py` içindeki `SECRET_KEY`'i üretim ortamında değiştirin.
- `catisma.db` dosyası ilk çalıştırmada otomatik oluşturulur.
