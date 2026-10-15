import asyncio
import ctypes
import json
import logging
import os
import subprocess
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

import keyring
import psutil
import pystray
from PIL import Image
from tapo import ApiClient
from winotify import Notification, audio

# ── Sabitler ─────────────────────────────────────────────────────────────
BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
AYAR_DOSYASI    = os.path.join(BASE_DIR, "ayarlar.json")
ICON_ON         = os.path.join(BASE_DIR, "icon_on.png")
ICON_OFF        = os.path.join(BASE_DIR, "icon_off.png")

KEYRING_SERVICE = "Pasa-Tapo"
MUTEX_NAME      = "Global\\Pasa-AkilliPriz-SingleInstance"

LOG_DIR         = os.path.join(os.environ.get("LOCALAPPDATA", BASE_DIR), "Pasa")
LOG_DOSYASI     = os.path.join(LOG_DIR, "pasa.log")

KONTROL_ARASI   = 5 * 60  # saniye

ERROR_ALREADY_EXISTS = 183

# ── Logging ───────────────────────────────────────────────────────────────
def log_kur():
    os.makedirs(LOG_DIR, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_DOSYASI, maxBytes=512_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
    ))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return logging.getLogger("pasa")

log = log_kur()

# ── Tek-instance kilidi ───────────────────────────────────────────────────
def tek_instance_kilit():
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        log.info("Zaten çalışan bir instance var, çıkılıyor.")
        sys.exit(0)
    return handle  # referansı canlı tut

# ── Kimlik bilgileri ──────────────────────────────────────────────────────
def kimlik_bilgisi_al():
    email = keyring.get_password(KEYRING_SERVICE, "email")
    sifre = keyring.get_password(KEYRING_SERVICE, "sifre")
    if not email or not sifre:
        log.error("Tapo kimlik bilgileri keyring'de yok. 'python kur.py' çalıştır.")
        bildirim_gonder("Paşa ⚠️", "Kurulum eksik — 'python kur.py' çalıştır.")
        sys.exit(2)
    return email, sifre

# ── Ayarlar ───────────────────────────────────────────────────────────────
def ayarlari_yukle():
    varsayilan = {
        "ust_esik": 80, "alt_esik": 20, "oto_kontrol": True,
        "priz_ip": "", "ev_aglari": [], "oyun_listesi": [],
    }
    if os.path.exists(AYAR_DOSYASI):
        try:
            with open(AYAR_DOSYASI, "r", encoding="utf-8") as f:
                return {**varsayilan, **json.load(f)}
        except (OSError, json.JSONDecodeError):
            log.exception("ayarlar.json okunamadı, varsayılanlar kullanılıyor.")
    return varsayilan

def ayarlari_kaydet(ayarlar):
    try:
        with open(AYAR_DOSYASI, "w", encoding="utf-8") as f:
            json.dump(ayarlar, f, indent=2, ensure_ascii=False)
    except OSError:
        log.exception("ayarlar.json yazılamadı.")

# ── Yardımcı fonksiyonlar ─────────────────────────────────────────────────
def pil_seviyesi():
    try:
        battery = psutil.sensors_battery()
        if battery:
            return int(battery.percent)
    except Exception:
        log.exception("Pil seviyesi okunamadı.")
    return None

def ev_aginda_mi(ev_aglari):
    if not ev_aglari:
        return True  # network check disabled
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
             "(Get-NetConnectionProfile).Name"],
            capture_output=True, text=True, timeout=5,
            creationflags=0x08000000  # CREATE_NO_WINDOW
        )
        ag = result.stdout.strip()
        return any(ev in ag for ev in ev_aglari)
    except (subprocess.SubprocessError, OSError):
        log.exception("Ağ adı okunamadı.")
        return False

def oyun_acik_mi(oyun_listesi):
    if not oyun_listesi:
        return False
    oyunlar = {o.lower() for o in oyun_listesi}
    try:
        for proc in psutil.process_iter(["name"]):
            if (proc.info["name"] or "").lower() in oyunlar:
                return True
    except Exception:
        log.exception("Süreç listesi okunamadı.")
    return False

def bildirim_gonder(baslik, mesaj):
    try:
        toast = Notification(
            app_id="Paşa - Akıllı Priz",
            title=baslik,
            msg=mesaj,
            duration="short",
        )
        toast.set_audio(audio.Default, loop=False)
        toast.show()
    except Exception:
        log.exception("Bildirim gönderilemedi.")

# ── Uygulama ──────────────────────────────────────────────────────────────
class Uygulama:
    def __init__(self):
        self.ayarlar = ayarlari_yukle()
        if not self.ayarlar["priz_ip"]:
            log.error("ayarlar.json içinde priz_ip boş.")
            bildirim_gonder("Paşa ⚠️", "ayarlar.json içinde priz_ip boş.")
            sys.exit(2)
        self.email, self.sifre = kimlik_bilgisi_al()
        self.tray = None
        self.priz_acik = None
        self.loop = asyncio.new_event_loop()
        self._device = None

    def async_calistir(self, coro, timeout=15):
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        try:
            return future.result(timeout=timeout)
        except TimeoutError:
            future.cancel()
            raise

    async def _cihaz_al(self):
        if self._device is None:
            client = ApiClient(self.email, self.sifre)
            self._device = await client.p115(self.ayarlar["priz_ip"])
        return self._device

    async def _priz_ac(self):
        dev = await self._cihaz_al()
        await dev.on()

    async def _priz_kapat(self):
        dev = await self._cihaz_al()
        await dev.off()

    async def _priz_durum(self):
        dev = await self._cihaz_al()
        info = await dev.get_device_info()
        return info.device_on

    def ikonu_guncelle(self, acik):
        self.priz_acik = acik
        try:
            img = Image.open(ICON_ON if acik else ICON_OFF)
            if self.tray:
                self.tray.icon = img
        except (OSError, FileNotFoundError):
            log.exception("İkon yüklenemedi.")

    def menu_guncelle(self):
        if self.tray:
            self.tray.menu = self.menu_olustur()

    def menu_olustur(self):
        oto  = self.ayarlar["oto_kontrol"]
        ust  = self.ayarlar["ust_esik"]
        alt  = self.ayarlar["alt_esik"]
        pil  = pil_seviyesi()
        evde = ev_aginda_mi(self.ayarlar["ev_aglari"])

        return pystray.Menu(
            pystray.MenuItem(
                f"Priz: {'✅ Açık' if self.priz_acik else '❌ Kapalı'}",
                None, enabled=False),
            pystray.MenuItem(
                f"Pil: %{pil if pil is not None else '?'}",
                None, enabled=False),
            pystray.MenuItem(
                f"Ağ: {'🏠 Evde' if evde else '🌍 Dışarıda'}",
                None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Prizi Aç",    self.manuel_ac),
            pystray.MenuItem("Prizi Kapat", self.manuel_kapat),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                f"Oto Kontrol: {'Açık ✅' if oto else 'Kapalı ❌'}",
                self.oto_toggle),
            pystray.MenuItem(
                f"Eşikler: %{alt} aç / %{ust} kapat",
                None, enabled=False),
            pystray.MenuItem("Eşiği Değiştir", pystray.Menu(
                pystray.MenuItem("Kapat eşiği: %75", lambda i, it: self.esik_ayarla("ust", 75)),
                pystray.MenuItem("Kapat eşiği: %80", lambda i, it: self.esik_ayarla("ust", 80)),
                pystray.MenuItem("Kapat eşiği: %85", lambda i, it: self.esik_ayarla("ust", 85)),
                pystray.MenuItem("Kapat eşiği: %90", lambda i, it: self.esik_ayarla("ust", 90)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Aç eşiği: %15", lambda i, it: self.esik_ayarla("alt", 15)),
                pystray.MenuItem("Aç eşiği: %20", lambda i, it: self.esik_ayarla("alt", 20)),
                pystray.MenuItem("Aç eşiği: %25", lambda i, it: self.esik_ayarla("alt", 25)),
            )),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Çıkış", self.cikis),
        )

    # ── Menü eylemleri ───────────────────────────────────────────────────
    def manuel_ac(self, icon=None, item=None):
        try:
            self.async_calistir(self._priz_ac())
            self.ikonu_guncelle(True)
            self.menu_guncelle()
            bildirim_gonder("Paşa Açıldı 🟢", "Priz manuel olarak açıldı.")
            log.info("Manuel aç.")
        except Exception as e:
            self._device = None
            log.exception("Manuel aç başarısız.")
            bildirim_gonder("Hata ⚠️", str(e)[:100])

    def manuel_kapat(self, icon=None, item=None):
        try:
            self.async_calistir(self._priz_kapat())
            self.ikonu_guncelle(False)
            self.menu_guncelle()
            bildirim_gonder("Paşa Kapandı 🔴", "Priz manuel olarak kapatıldı.")
            log.info("Manuel kapat.")
        except Exception as e:
            self._device = None
            log.exception("Manuel kapat başarısız.")
            bildirim_gonder("Hata ⚠️", str(e)[:100])

    def oto_toggle(self, icon=None, item=None):
        self.ayarlar["oto_kontrol"] = not self.ayarlar["oto_kontrol"]
        ayarlari_kaydet(self.ayarlar)
        self.menu_guncelle()
        durum = "açıldı ✅" if self.ayarlar["oto_kontrol"] else "kapatıldı ❌"
        bildirim_gonder("Oto Kontrol", f"Otomatik kontrol {durum}.")
        log.info("Oto kontrol %s.", durum)

    def esik_ayarla(self, tip, deger):
        self.ayarlar["ust_esik" if tip == "ust" else "alt_esik"] = deger
        ayarlari_kaydet(self.ayarlar)
        self.menu_guncelle()
        bildirim_gonder("Eşik Güncellendi",
            f"{'Kapatma' if tip == 'ust' else 'Açma'} eşiği %{deger} olarak ayarlandı.")
        log.info("Eşik %s=%s", tip, deger)

    def cikis(self, icon=None, item=None):
        log.info("Çıkış.")
        if self.tray:
            self.tray.stop()

    # ── Oto kontrol döngüsü ──────────────────────────────────────────────
    def kontrol_dongusu(self):
        while True:
            try:
                if not self.ayarlar["oto_kontrol"]:
                    pass
                elif not ev_aginda_mi(self.ayarlar["ev_aglari"]):
                    pass
                elif oyun_acik_mi(self.ayarlar["oyun_listesi"]):
                    acik = self.async_calistir(self._priz_durum())
                    self.ikonu_guncelle(acik)
                    self.menu_guncelle()
                    if not acik:
                        self.async_calistir(self._priz_ac())
                        self.ikonu_guncelle(True)
                        self.menu_guncelle()
                        bildirim_gonder("Paşa Açıldı 🟢", "Oyun açık, şarj başlatıldı.")
                        log.info("Oyun modu — priz kapalıydı, açıldı.")
                else:
                    pil = pil_seviyesi()
                    if pil is not None:
                        acik = self.async_calistir(self._priz_durum())
                        self.ikonu_guncelle(acik)
                        self.menu_guncelle()

                        if pil >= self.ayarlar["ust_esik"] and acik:
                            self.async_calistir(self._priz_kapat())
                            self.ikonu_guncelle(False)
                            self.menu_guncelle()
                            bildirim_gonder("Paşa Kapandı 🔴", f"Pil %{pil} oldu, şarj kesildi.")
                            log.info("Oto kapat — pil %%%s", pil)

                        elif pil <= self.ayarlar["alt_esik"] and not acik:
                            self.async_calistir(self._priz_ac())
                            self.ikonu_guncelle(True)
                            self.menu_guncelle()
                            bildirim_gonder("Paşa Açıldı 🟢", f"Pil %{pil}'e düştü, şarj başladı.")
                            log.info("Oto aç — pil %%%s", pil)
            except Exception:
                self._device = None
                log.exception("Kontrol döngüsünde hata.")
            time.sleep(KONTROL_ARASI)

    # ── Başlat ───────────────────────────────────────────────────────────
    def baslat(self):
        log.info("Paşa başlatılıyor.")
        threading.Thread(target=self.loop.run_forever, daemon=True).start()

        try:
            acik = self.async_calistir(self._priz_durum())
            self.priz_acik = acik
        except Exception:
            self.priz_acik = False
            self._device = None
            log.exception("İlk priz durumu alınamadı.")

        threading.Thread(target=self.kontrol_dongusu, daemon=True).start()

        try:
            img = Image.open(ICON_ON if self.priz_acik else ICON_OFF)
        except (OSError, FileNotFoundError):
            log.exception("İkon dosyası yüklenemedi, çıkılıyor.")
            sys.exit(1)

        self.tray = pystray.Icon(
            "Paşa", img, "Paşa - Akıllı Priz",
            menu=self.menu_olustur(),
        )
        self.tray.run()


if __name__ == "__main__":
    _mutex = tek_instance_kilit()
    try:
        Uygulama().baslat()
    except Exception:
        log.exception("Ölümcül hata — uygulama sonlandı.")
        raise
