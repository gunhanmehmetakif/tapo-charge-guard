# tapo-charge-guard

Laptop şarjını TP-Link Tapo akıllı priz ile belirli bir aralıkta (ör. %25–%90) tutan Windows tray uygulaması. Pilin sürekli %100'de kalmasını önleyerek ömrünü uzatmayı amaçlar.

## Ne yapar

- Pil seviyesini 5 dakikada bir kontrol eder.
- Pil üst eşiğe ulaşınca prizi kapatır, alt eşiğe düşünce açar.
- Bu kontrolü yalnız ev ağındayken yapar. Ev ağı listesi boş bırakılırsa her ağda çalışır.
- Listedeki bir oyun açıksa prizi açık tutar.
- Tray menüsünden priz elle açılıp kapatılabilir, otomatik kontrol açılıp kapatılabilir ve eşikler değiştirilebilir.
- Durum değişikliklerini Windows bildirimi olarak gösterir.

## Gereksinimler

- Windows 10/11, Python 3.10+
- Tapo P110/P115 akıllı priz (yerel ağda erişilebilir, sabit IP önerilir)

## Kurulum

```powershell
pip install -r requirements.txt
copy ayarlar.example.json ayarlar.json
python kur.py
```

`kur.py` Tapo e-posta adresini ve şifresini **Windows Credential Manager**'a kaydeder. Şifre hiçbir dosyaya yazılmaz.

Ardından `ayarlar.json` dosyasını düzenle:

| Anahtar | Açıklama |
|---|---|
| `priz_ip` | Prizin yerel IP adresi (zorunlu) |
| `ust_esik` / `alt_esik` | Prizin kapanacağı ve açılacağı pil yüzdesi |
| `oto_kontrol` | Otomatik kontrol açık mı |
| `ev_aglari` | Ev Wi-Fi adları. Boş liste verilirse ağ kontrolü yapılmaz |
| `oyun_listesi` | Açıkken prizin açık tutulacağı süreç adları |

Çalıştırmak için:

```powershell
pythonw priz.py
```

## Oturum açılışında otomatik başlatma

`PasaTray.example.xml` dosyasını `PasaTray.xml` adıyla kopyala. İçindeki `BILGISAYAR\KULLANICI` ve `C:\YOL\...` yer tutucularını kendi bilgilerinle değiştir. Sonra görevi içe aktar:

```powershell
schtasks /Create /TN "PasaTray" /XML PasaTray.xml
```

Loglar `%LOCALAPPDATA%\Pasa\pasa.log` dosyasına yazılır.
