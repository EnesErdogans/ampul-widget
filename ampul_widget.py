"""
Ampul - Fonri / Tuya akıllı ampulü masaüstünden kontrol eden widget.

Geliştirme için çalıştırma:
    pip install tinytuya tuya-device-sharing-sdk qrcode
    pythonw ampul_widget.py
Exe olarak kurmak için kur.bat dosyasını çalıştır.

- Ampul ve local key Tuya IoT projesinden alınır; olmazsa Smart Life QR girişi açılır.
- Komutlar önce yerel ağdan gider (hızlı); olmazsa bulut üzerinden gönderilir.
- Başlıktan sürükle, "–" ile görev çubuğuna küçült, sağ tıkla menüyü aç.
"""
import colorsys
import json
import math
import os
import queue
import sys
import threading
import time
import tkinter as tk

import qrcode
import tinytuya
from tuya_sharing import LoginControl, Manager, SharingTokenListener

# ---- Tuya IoT proje bilgileri (iot.tuya.com) ---------------------------
API_REGION = "eu"  # Central Europe Data Center
REGIONS = ["eu", "eu-w"]
API_KEY = ""     # .env dosyasindan okunur (TUYA_API_KEY)
API_SECRET = ""  # .env dosyasindan okunur (TUYA_API_SECRET)
# ---- Yedek: Smart Life QR girişi (Home Assistant'ın Tuya girişiyle aynı) --
TUYA_CLIENT_ID = "HA_3y9q4ak7g4ephrvke"
TUYA_SCHEMA = "haauthorize"
# -----------------------------------------------------------------------

APP_NAME = "Ampul"
BASE = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, "frozen", False) else __file__))
if sys.platform == "win32" and os.environ.get("APPDATA"):
    DATA_DIR = os.path.join(os.environ["APPDATA"], "AmpulWidget")
else:
    DATA_DIR = BASE
os.makedirs(DATA_DIR, exist_ok=True)
CONFIG_PATH = os.path.join(DATA_DIR, "ampul_config.json")


def _env_yukle():
    """Uygulama klasorundeki (veya %APPDATA%\\AmpulWidget) .env dosyasini okur."""
    for klasor in (BASE, DATA_DIR):
        yol = os.path.join(klasor, ".env")
        if not os.path.isfile(yol):
            continue
        with open(yol, encoding="utf-8") as f:
            for satir in f:
                satir = satir.strip()
                if satir and not satir.startswith("#") and "=" in satir:
                    k, v = satir.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_env_yukle()
API_KEY = os.environ.get("TUYA_API_KEY", API_KEY)
API_SECRET = os.environ.get("TUYA_API_SECRET", API_SECRET)
API_REGION = os.environ.get("TUYA_API_REGION", API_REGION)


def kaynak(ad):
    return os.path.join(getattr(sys, "_MEIPASS", BASE), ad)


BG = "#15161a"
PANEL = "#1d1f24"
CARD = "#2b2d34"
FG = "#ececee"
MUTED = "#8b8d96"
ACCENT = "#3d9bff"
OFF = "#3a3c44"
ERR = "#ff6b6b"
OK = "#34c759"
SWATCHES = ["#ff3b30", "#ff9500", "#ffcc00", "#34c759",
            "#00c7be", "#007aff", "#af52de", "#ff2d92"]
LIGHT_CATEGORIES = {"dj", "dd", "fwd", "dc", "xdd", "fwl", "tgq", "tyndj"}
FONT = "Segoe UI"
WARM, MID, COOL = (247, 196, 92), (246, 240, 214), (178, 240, 255)


def load_cfg():
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cfg(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def hexc(rgb):
    return "#%02x%02x%02x" % tuple(int(clamp(c, 0, 255)) for c in rgb)


def temp_rgb(t):
    """0 = sıcak sarı, 1 = soğuk beyaz"""
    if t < 0.5:
        a, b, k = WARM, MID, t / 0.5
    else:
        a, b, k = MID, COOL, (t - 0.5) / 0.5
    return tuple(a[i] + (b[i] - a[i]) * k for i in range(3))


def hue_rgb(t, s=1.0):
    return tuple(c * 255 for c in colorsys.hsv_to_rgb(t % 1, s, 1))


class KurulumGerekli(Exception):
    pass


# ======================================================================
#  Bulut bağlantıları
# ======================================================================
class IoTBulut:
    """Tuya IoT geliştirici projesi üzerinden."""

    def __init__(self, region):
        self.c = tinytuya.Cloud(apiRegion=region, apiKey=API_KEY, apiSecret=API_SECRET)

    def cihazlar(self):
        d = self.c.getdevices()
        if not isinstance(d, list):
            raise RuntimeError(str(d)[:150])
        return [{"id": x["id"], "key": x.get("key"), "name": x.get("name") or x["id"],
                 "category": x.get("category", "")} for x in d]

    def durum(self, dev_id):
        r = self.c.getstatus(dev_id)
        return {i["code"]: i["value"] for i in r.get("result", [])}

    def komut(self, dev_id, cmds):
        r = self.c.sendcommand(dev_id, {"commands": cmds})
        if isinstance(r, dict) and r.get("success") is False:
            raise RuntimeError(r.get("msg", "Komut reddedildi"))


class TokenKaydet(SharingTokenListener):
    def __init__(self, cfg):
        self.cfg = cfg

    def update_token(self, token_info):
        if "auth" in self.cfg:
            self.cfg["auth"]["token"] = token_info
            save_cfg(self.cfg)


class QRBulut:
    """Smart Life QR girişi üzerinden (geliştirici projesi gerekmez)."""

    def __init__(self, cfg):
        a = cfg["auth"]
        self.m = Manager(TUYA_CLIENT_ID, a["user_code"], a["terminal_id"],
                         a["endpoint"], a["token"], TokenKaydet(cfg))

    def cihazlar(self):
        self.m.update_device_cache()
        return [{"id": d.id, "key": d.local_key, "name": d.name or d.id,
                 "category": getattr(d, "category", "")} for d in self.m.device_map.values()]

    def durum(self, dev_id):
        self.m._update_device_list_info_cache([dev_id])
        d = self.m.device_map.get(dev_id)
        return dict(getattr(d, "status", {}) or {})

    def komut(self, dev_id, cmds):
        cmds = [{"code": c["code"],
                 "value": json.dumps(c["value"]) if isinstance(c["value"], dict) else c["value"]}
                for c in cmds]
        self.m.send_commands(dev_id, cmds)


def qr_olustur(user_code):
    lc = LoginControl()
    r = lc.qr_code(TUYA_CLIENT_ID, TUYA_SCHEMA, user_code)
    if not r.get("success"):
        raise RuntimeError(r.get("msg") or "QR oluşturulamadı, kullanıcı kodunu kontrol et")
    return lc, r["result"]["qrcode"]


def qr_sonuc(lc, token, user_code):
    ok, info = lc.login_result(token, TUYA_CLIENT_ID, user_code)
    if not ok:
        return None
    return {"user_code": user_code, "terminal_id": info["terminal_id"],
            "endpoint": info["endpoint"],
            "token": {k: info[k] for k in ("t", "uid", "expire_time", "access_token", "refresh_token")}}


# ======================================================================
#  Ampul
# ======================================================================
VARSAYILAN = {"on": True, "mode": "white", "bright": 100, "temp": 50, "h": 0, "s": 100, "v": 100}


class Ampul:
    def __init__(self, cfg):
        self.cfg = cfg
        self.local = None
        self._bulut = None
        self.mode = None  # "local" | "cloud"

    def bulut(self):
        if self._bulut is None:
            if self.cfg.get("auth"):
                self._bulut = QRBulut(self.cfg)
            else:
                self._bulut = IoTBulut(self.cfg.get("region") or API_REGION)
        return self._bulut

    def sifirla(self):
        self.local = None
        self._bulut = None
        self.mode = None

    # ---------- kurulum ----------
    def kur(self):
        self.local = None
        if not self.cfg.get("id") or not self.cfg.get("key"):
            self.cihazlari_al()
        st = self._yerel_dene()
        if st is None:  # IP bilinmiyor ya da değişmiş olabilir
            self._ip_bul()
            st = self._yerel_dene()
        if st is not None:
            self.mode = "local"
            return st
        self.mode = "cloud"
        try:
            return self._kod_coz(self.bulut().durum(self.cfg["id"]))
        except Exception:
            return dict(VARSAYILAN)

    def cihazlari_al(self):
        devs, hata = [], ""
        if self.cfg.get("auth"):
            devs = self.bulut().cihazlar()
        else:
            for reg in REGIONS:
                try:
                    b = IoTBulut(reg)
                    d = b.cihazlar()
                except Exception as e:
                    hata = str(e)
                    continue
                if d:
                    devs, self._bulut = d, b
                    self.cfg["region"] = reg
                    break
        if not devs:
            raise KurulumGerekli(hata or "Tuya projesinde cihaz bulunamadı")
        isiklar = [d for d in devs if d["category"] in LIGHT_CATEGORIES] or devs
        d = isiklar[0]
        self.cfg.update(id=d["id"], key=d["key"], name=d["name"], ip=None)
        self.cfg["devices"] = [{k: x[k] for k in ("id", "key", "name")} for x in isiklar]
        save_cfg(self.cfg)

    def _ip_bul(self):
        try:
            r = tinytuya.find_device(self.cfg["id"])
            if r and r.get("ip"):
                self.cfg["ip"] = r["ip"]
                if r.get("version"):
                    self.cfg["version"] = str(r["version"])
        except Exception:
            pass

    def _yerel_dene(self):
        ip = self.cfg.get("ip")
        if not ip:
            return None
        try:
            d = tinytuya.BulbDevice(self.cfg["id"], ip, self.cfg["key"])
            d.set_version(float(self.cfg.get("version") or 3.3))
            d.set_socketTimeout(3)
            st = d.status()
            if not st or "Error" in st or "dps" not in st:
                return None
            self.local = d
            return self._dps_coz(st["dps"])
        except Exception:
            return None

    # ---------- durum çözme ----------
    @staticmethod
    def _dps_coz(dps):
        s = dict(VARSAYILAN)
        if "20" in dps:
            s["on"] = bool(dps.get("20", True))
            s["mode"] = dps.get("21", "white")
            s["bright"] = clamp(dps.get("22", 1000) / 10, 1, 100)
            s["temp"] = clamp(dps.get("23", 500) / 10, 0, 100)
            col = dps.get("24")
            if isinstance(col, str) and len(col) == 12:
                s["h"] = int(col[0:4], 16)
                s["s"] = int(col[4:8], 16) / 10
                s["v"] = clamp(int(col[8:12], 16) / 10, 1, 100)
        else:
            s["on"] = bool(dps.get("1", True))
            s["mode"] = dps.get("2", "white")
            s["bright"] = clamp((dps.get("3", 255) - 25) / 230 * 100, 1, 100)
            s["temp"] = clamp(dps.get("4", 128) / 255 * 100, 0, 100)
        return s

    @staticmethod
    def _kod_coz(status):
        s = dict(VARSAYILAN)
        s["on"] = bool(status.get("switch_led", True))
        s["mode"] = status.get("work_mode", "white")
        if "bright_value_v2" in status:
            s["bright"] = clamp(status["bright_value_v2"] / 10, 1, 100)
        if "temp_value_v2" in status:
            s["temp"] = clamp(status["temp_value_v2"] / 10, 0, 100)
        col = status.get("colour_data_v2")
        if isinstance(col, str) and col:
            try:
                col = json.loads(col)
            except Exception:
                col = None
        if isinstance(col, dict):
            s["h"] = col.get("h", 0)
            s["s"] = col.get("s", 1000) / 10
            s["v"] = clamp(col.get("v", 1000) / 10, 1, 100)
        return s

    # ---------- komutlar ----------
    def _calistir(self, yerel_fn, bulut_komutlari):
        if self.mode == "local" and self.local is not None:
            try:
                r = yerel_fn(self.local)
                if not (isinstance(r, dict) and "Error" in r):
                    return
            except Exception:
                pass
            self.mode = "cloud"
        self.bulut().komut(self.cfg["id"], bulut_komutlari)

    def guc(self, on):
        self._calistir(lambda d: d.turn_on() if on else d.turn_off(),
                       [{"code": "switch_led", "value": bool(on)}])

    def beyaz(self, bright, temp):
        self._calistir(
            lambda d: d.set_white_percentage(int(bright), int(temp)),
            [{"code": "switch_led", "value": True},
             {"code": "work_mode", "value": "white"},
             {"code": "bright_value_v2", "value": int(clamp(bright * 10, 10, 1000))},
             {"code": "temp_value_v2", "value": int(clamp(temp * 10, 0, 1000))}])

    def renk(self, h, s, v):
        self._calistir(
            lambda d: d.set_hsv((h % 360) / 360, clamp(s, 0, 100) / 100, clamp(v, 1, 100) / 100),
            [{"code": "switch_led", "value": True},
             {"code": "work_mode", "value": "colour"},
             {"code": "colour_data_v2", "value": {
                 "h": int(h) % 360,
                 "s": int(clamp(s * 10, 0, 1000)),
                 "v": int(clamp(v * 10, 10, 1000))}}])


# ======================================================================
#  Çizim bileşenleri
# ======================================================================
class Kadran(tk.Canvas):
    """Telefondaki gibi halka kadran. tur='temp' (270° yay) veya 'hue' (tam çember)."""

    def __init__(self, master, tur, degisti, merkez_tik, size=236):
        super().__init__(master, width=size, height=size, bg=PANEL, highlightthickness=0)
        self.tur, self.degisti, self.merkez_tik = tur, degisti, merkez_tik
        self.cx = self.cy = size / 2
        self.T = 34
        self.R = size / 2 - self.T / 2 - 8
        self.t = 0.0
        self.sat = 1.0
        self.merkez = (OFF, False)
        self._surukle = False
        self._halka()
        self._ciz_dinamik()
        self.bind("<Button-1>", self._bas)
        self.bind("<B1-Motion>", self._fare)
        self.bind("<ButtonRelease-1>", self._birak)

    def _aci(self, t):
        return 225 - 270 * t if self.tur == "temp" else 90 - 360 * t

    def _renk(self, t):
        return temp_rgb(t) if self.tur == "temp" else hue_rgb(t, self.sat)

    def _nokta(self, t, r=None):
        a = math.radians(self._aci(t))
        r = self.R if r is None else r
        return self.cx + r * math.cos(a), self.cy - r * math.sin(a)

    def _halka(self):
        self.delete("halka")
        n = 90 if self.tur == "temp" else 120
        span = 270 if self.tur == "temp" else 360
        bb = (self.cx - self.R, self.cy - self.R, self.cx + self.R, self.cy + self.R)
        for i in range(n):
            a0 = self._aci(i / n)
            ext = -(span / n + (1.2 if i < n - 1 or self.tur == "hue" else 0))
            self.create_arc(*bb, start=a0, extent=ext, style="arc", width=self.T,
                            outline=hexc(self._renk((i + 0.5) / n)), tags="halka")
        if self.tur == "temp":  # yuvarlak uçlar
            for t in (0, 1):
                x, y = self._nokta(t)
                r = self.T / 2
                self.create_oval(x - r, y - r, x + r, y + r, fill=hexc(self._renk(t)),
                                 outline="", tags="halka")

    def doygunluk(self, s):
        if self.tur == "hue" and abs(s - self.sat) > 0.02:
            self.sat = s
            self._halka()
            self.tag_raise("dinamik")

    def ayarla(self, t=None, merkez=None):
        if t is not None:
            self.t = clamp(t, 0, 1)
        if merkez is not None:
            self.merkez = merkez
        self._ciz_dinamik()

    def _ciz_dinamik(self):
        self.delete("dinamik")
        # merkez düğme
        col, on = self.merkez
        r = 52
        self.create_oval(self.cx - r, self.cy - r, self.cx + r, self.cy + r,
                         fill=col if on else CARD, outline="", tags="dinamik")
        ic = "#1c1d22" if on else MUTED
        self.create_arc(self.cx - 16, self.cy - 14, self.cx + 16, self.cy + 18, start=120,
                        extent=300, style="arc", outline=ic, width=3, tags="dinamik")
        self.create_line(self.cx, self.cy - 20, self.cx, self.cy - 2, fill=ic, width=3,
                         capstyle="round", tags="dinamik")
        # topuz
        x, y = self._nokta(self.t)
        k = self.T / 2 + 5
        self.create_oval(x - k, y - k, x + k, y + k, fill=hexc(self._renk(self.t)),
                         outline="white", width=4, tags="dinamik")

    def _bas(self, e):
        d = math.hypot(e.x - self.cx, e.y - self.cy)
        if d < 54:
            self.merkez_tik()
            return
        if abs(d - self.R) < self.T:
            self._surukle = True
            self._fare(e)

    def _fare(self, e):
        if not self._surukle:
            return
        a = math.degrees(math.atan2(-(e.y - self.cy), e.x - self.cx))
        if self.tur == "temp":
            off = (225 - a) % 360
            if off > 270:
                off = 270 if off < 315 else 0
            t = off / 270
        else:
            t = ((90 - a) % 360) / 360
        self.t = t
        self._ciz_dinamik()
        self.degisti(t, False)

    def _birak(self, e):
        if self._surukle:
            self._surukle = False
            self.degisti(self.t, True)


class Surgu(tk.Canvas):
    def __init__(self, master, lo, hi, degisti, w=196, h=30):
        super().__init__(master, width=w, height=h, bg=PANEL, highlightthickness=0, cursor="hand2")
        self.lo, self.hi, self.degisti, self.w, self.h = lo, hi, degisti, w, h
        self.pad = 12
        self.deger = hi
        self.renk = "#cfcfd4"
        self.bind("<Button-1>", self._fare)
        self.bind("<B1-Motion>", self._fare)
        self.bind("<ButtonRelease-1>", lambda e: self.degisti(self.deger, True))
        self._ciz()

    def ayarla(self, v=None, renk=None):
        if v is not None:
            self.deger = clamp(v, self.lo, self.hi)
        if renk:
            self.renk = renk
        self._ciz()

    def _ciz(self):
        self.delete("all")
        y = self.h / 2
        x = self.pad + (self.deger - self.lo) / (self.hi - self.lo) * (self.w - 2 * self.pad)
        self.create_line(self.pad, y, self.w - self.pad, y, fill=CARD, width=8, capstyle="round")
        self.create_line(self.pad, y, x, y, fill=self.renk, width=8, capstyle="round")
        self.create_oval(x - 11, y - 11, x + 11, y + 11, fill="white", outline="")

    def _fare(self, e):
        t = clamp((e.x - self.pad) / (self.w - 2 * self.pad), 0, 1)
        self.deger = self.lo + t * (self.hi - self.lo)
        self._ciz()
        self.degisti(self.deger, False)


# ======================================================================
#  Pencere
# ======================================================================
class Widget(tk.Tk):
    W, H = 290, 480

    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.cfg = load_cfg()
        self.ampul = Ampul(self.cfg)
        self.st = dict(VARSAYILAN)
        self.st["on"] = False
        self.sekme = "white"
        self._deb = None
        self._drag = (0, 0)
        self._qr = None
        self._hwnd = None

        self.q = queue.Queue()      # arka plan işleri
        self.ui_q = queue.Queue()   # arka plandan arayüze dönen işler
        threading.Thread(target=self._worker, daemon=True).start()
        self.after(40, self._ui_pompa)

        try:
            if sys.platform == "win32":
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ampulwidget")
                self.iconbitmap(default=kaynak("ampul.ico"))
        except Exception:
            pass

        self.overrideredirect(True)
        self.attributes("-topmost", self.cfg.get("topmost", True))
        self.configure(bg=PANEL, highlightthickness=1, highlightbackground="#33353d")
        x, y = self.cfg.get("x"), self.cfg.get("y")
        if x is None:
            x, y = self.winfo_screenwidth() - self.W - 40, 80
        self.geometry(f"{self.W}x{self.H}+{x}+{y}")

        self.topmost_var = tk.BooleanVar(value=self.cfg.get("topmost", True))
        self.menu = tk.Menu(self, tearoff=0)
        self.bind("<Button-3>", self._menu_ac)

        self._baslik()
        self.setup = tk.Frame(self, bg=PANEL)
        self.ctrl = tk.Frame(self, bg=PANEL)
        self._kurulum_arayuz()
        self._kontrol_arayuz()
        self.after(60, self._gorev_cubugu)

        if self.cfg.get("auth") or self.cfg.get("id") or API_KEY:
            self._kontrol_goster()
        else:
            self._kurulum_goster()

    # ---------- görev çubuğu / küçültme ----------
    def _gorev_cubugu(self):
        """Çerçevesiz pencerenin görev çubuğunda görünmesini sağlar (Windows)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes
            u = ctypes.windll.user32
            self._hwnd = u.GetParent(self.winfo_id())
            GWL_EXSTYLE, WS_EX_APPWINDOW, WS_EX_TOOLWINDOW = -20, 0x40000, 0x80
            st = u.GetWindowLongW(self._hwnd, GWL_EXSTYLE)
            u.SetWindowLongW(self._hwnd, GWL_EXSTYLE, (st & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW)
            self.withdraw()
            self.after(10, self.deiconify)
        except Exception:
            self._hwnd = None

    def _kucult(self):
        if self._hwnd:
            import ctypes
            ctypes.windll.user32.ShowWindow(self._hwnd, 6)  # SW_MINIMIZE
            return
        # Windows dışı yedek yöntem
        self.overrideredirect(False)
        self.iconify()

        def geri(e):
            if self.state() == "normal":
                self.overrideredirect(True)
                self.unbind("<Map>")
        self.bind("<Map>", geri)

    # ---------- başlık ----------
    def _baslik(self):
        hdr = tk.Frame(self, bg=PANEL)
        hdr.pack(fill="x", padx=12, pady=(8, 0))
        self.dot = tk.Label(hdr, text="●", fg=MUTED, bg=PANEL, font=(FONT, 9))
        self.dot.pack(side="left")
        self.title_lbl = tk.Label(hdr, text=self.cfg.get("name", APP_NAME), fg=FG, bg=PANEL,
                                  font=(FONT, 11, "bold"))
        self.title_lbl.pack(side="left", padx=(5, 0))
        close = tk.Label(hdr, text="×", fg=MUTED, bg=PANEL, font=(FONT, 11), cursor="hand2")
        close.pack(side="right", padx=(6, 0))
        close.bind("<Button-1>", lambda e: self._kapat())
        mini = tk.Label(hdr, text="—", fg=MUTED, bg=PANEL, font=(FONT, 11), cursor="hand2")
        mini.pack(side="right", padx=6)
        mini.bind("<Button-1>", lambda e: self._kucult())
        for w, h in ((close, ERR), (mini, FG)):
            w.bind("<Enter>", lambda e, w=w, h=h: w.config(fg=h))
            w.bind("<Leave>", lambda e, w=w: w.config(fg=MUTED))
        for w in (hdr, self.title_lbl, self.dot):
            w.bind("<ButtonPress-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)

    # ---------- kontrol ekranı ----------
    def _kontrol_arayuz(self):
        f = self.ctrl
        # sekmeler
        tabs = tk.Frame(f, bg=PANEL)
        tabs.pack(fill="x", padx=16, pady=(8, 0))
        self.tab_lbl = {}
        for kod, ad in (("white", "Beyaz/Sarı"), ("colour", "Renkli")):
            col = tk.Frame(tabs, bg=PANEL)
            col.pack(side="left", expand=True, fill="x")
            lbl = tk.Label(col, text=ad, fg=MUTED, bg=PANEL, font=(FONT, 10), cursor="hand2")
            lbl.pack()
            bar = tk.Frame(col, bg=PANEL, height=3, width=34)
            bar.pack(pady=(3, 0))
            for w in (lbl, col):
                w.bind("<Button-1>", lambda e, k=kod: self._sekme_sec(k, gonder=True))
            self.tab_lbl[kod] = (lbl, bar)
        tk.Frame(f, bg="#2a2c33", height=1).pack(fill="x", padx=10)

        self.sayfa_beyaz = tk.Frame(f, bg=PANEL)
        self.sayfa_renk = tk.Frame(f, bg=PANEL)

        # Beyaz/Sarı
        p = self.sayfa_beyaz
        self.k_temp = Kadran(p, "temp", self._temp_degisti, self._guc_degistir)
        self.k_temp.pack(pady=(14, 8))
        self.s_bright, self.l_bright = self._surgu_satir(p, "☀", 1, 100, self._bright_degisti)

        # Renkli
        p = self.sayfa_renk
        self.k_hue = Kadran(p, "hue", self._hue_degisti, self._guc_degistir)
        self.k_hue.pack(pady=(14, 4))
        self.s_sat, self.l_sat = self._surgu_satir(p, "◐", 0, 100, self._sat_degisti)
        self.s_v, self.l_v = self._surgu_satir(p, "☀", 1, 100, self._v_degisti)
        row = tk.Frame(p, bg=PANEL)
        row.pack(pady=(6, 0))
        for h in SWATCHES:
            c = tk.Canvas(row, width=22, height=22, bg=PANEL, highlightthickness=0, cursor="hand2")
            c.create_oval(2, 2, 20, 20, fill=h, outline="")
            c.pack(side="left", padx=3)
            c.bind("<Button-1>", lambda e, h=h: self._hazir_renk(h))

        self.footer = tk.Label(f, text="", fg=MUTED, bg=PANEL, font=(FONT, 8),
                               wraplength=self.W - 30, justify="center")
        self.footer.pack(side="bottom", pady=(0, 8))
        self._sekme_sec("white")

    def _surgu_satir(self, master, ikon, lo, hi, cmd):
        row = tk.Frame(master, bg=PANEL)
        row.pack(fill="x", padx=14, pady=2)
        tk.Label(row, text=ikon, fg=FG, bg=PANEL, font=(FONT, 12), width=2).pack(side="left")
        s = Surgu(row, lo, hi, cmd)
        s.pack(side="left", padx=(2, 4))
        lbl = tk.Label(row, text="", fg=FG, bg=PANEL, font=(FONT, 10), width=5, anchor="e")
        lbl.pack(side="left")
        return s, lbl

    def _sekme_sec(self, kod, gonder=False):
        self.sekme = kod
        for k, (lbl, bar) in self.tab_lbl.items():
            aktif = k == kod
            lbl.config(fg=ACCENT if aktif else FG, font=(FONT, 10, "bold" if aktif else "normal"))
            bar.config(bg=ACCENT if aktif else PANEL)
        self.sayfa_beyaz.pack_forget()
        self.sayfa_renk.pack_forget()
        (self.sayfa_beyaz if kod == "white" else self.sayfa_renk).pack(fill="both", expand=True)
        if gonder and self.st["on"] and self.st["mode"] != kod:
            self.st["mode"] = kod
            self._isik_gonder()
        self._yenile()

    def _kontrol_goster(self):
        self.setup.pack_forget()
        self.ctrl.pack(fill="both", expand=True)
        self.title_lbl.config(text=self.cfg.get("name", APP_NAME))
        self._durum_yaz("Bağlanıyor…")
        self.dot.config(fg=MUTED)
        self._gonder("init", self._baslat)

    # ---------- görünümü güncelle ----------
    def _isik_rengi(self):
        s = self.st
        if s["mode"] == "colour":
            return hexc(hue_rgb(s["h"] / 360, max(s["s"], 10) / 100))
        return hexc(temp_rgb(s["temp"] / 100))

    def _yenile(self):
        s = self.st
        col = self._isik_rengi()
        on = s["on"]
        self.k_temp.ayarla(s["temp"] / 100, (hexc(temp_rgb(s["temp"] / 100)) if s["mode"] == "white" else col, on))
        self.k_hue.doygunluk(max(s["s"], 10) / 100)
        self.k_hue.ayarla(s["h"] / 360, (col, on))
        self.s_bright.ayarla(s["bright"], hexc(temp_rgb(s["temp"] / 100)))
        self.s_sat.ayarla(s["s"], hexc(hue_rgb(s["h"] / 360)))
        self.s_v.ayarla(s["v"], hexc(hue_rgb(s["h"] / 360, max(s["s"], 10) / 100)))
        self.l_bright.config(text=f"%{int(s['bright'])}")
        self.l_sat.config(text=f"%{int(s['s'])}")
        self.l_v.config(text=f"%{int(s['v'])}")

    def _durum_yaz(self, txt, renk=MUTED):
        self.footer.config(text=txt, fg=renk)

    # ---------- arka plan işleri ----------
    def _worker(self):
        while True:
            items = [self.q.get()]
            try:
                while True:
                    items.append(self.q.get_nowait())
            except queue.Empty:
                pass
            latest = {}
            for kind, fn in items:  # aynı türden yalnızca son işi çalıştır
                latest.pop(kind, None)
                latest[kind] = fn
            for kind, fn in latest.items():
                try:
                    fn()
                    if kind in ("init", "guc", "isik"):
                        self._ui(self._mod_goster)
                except KurulumGerekli as e:
                    self._ui(self._kurulum_goster, str(e))
                except Exception as e:
                    msg = str(e).splitlines()[0][:90] if str(e) else type(e).__name__
                    self._ui(self._durum_yaz, "Hata: " + msg, ERR)

    def _ui(self, fn, *args):
        """Arka plan iş parçacığından arayüzü güvenle güncellemek için."""
        self.ui_q.put((fn, args))

    def _ui_pompa(self):
        try:
            while True:
                fn, args = self.ui_q.get_nowait()
                try:
                    fn(*args)
                except Exception:
                    pass
        except queue.Empty:
            pass
        self.after(40, self._ui_pompa)

    def _gonder(self, kind, fn):
        self.q.put((kind, fn))

    def _baslat(self):
        st = self.ampul.kur()
        save_cfg(self.cfg)
        self._ui(self._durum_uygula, st)

    def _durum_uygula(self, st):
        if st:
            self.st.update(st)
        self.title_lbl.config(text=self.cfg.get("name", APP_NAME))
        self._sekme_sec("colour" if self.st["mode"] == "colour" else "white")

    def _mod_goster(self):
        if self.ampul.mode == "local":
            self.dot.config(fg=OK)
            self._durum_yaz(f"Yerel ağ · {self.cfg.get('ip', '')}")
        elif self.ampul.mode == "cloud":
            self.dot.config(fg="#ffcc00")
            self._durum_yaz("Bulut üzerinden")

    # ---------- eylemler ----------
    def _guc_degistir(self):
        self.st["on"] = not self.st["on"]
        self._yenile()
        on = self.st["on"]
        self._gonder("guc", lambda: self.ampul.guc(on))

    def _isik_gonder(self):
        s = dict(self.st)
        if s["mode"] == "colour":
            self._gonder("isik", lambda: self.ampul.renk(s["h"], s["s"], s["v"]))
        else:
            self._gonder("isik", lambda: self.ampul.beyaz(s["bright"], s["temp"]))

    def _degisim(self, son, **kw):
        self.st.update(on=True, **kw)
        self._yenile()
        if self._deb:
            self.after_cancel(self._deb)
            self._deb = None
        if son:
            self._isik_gonder()
        else:
            self._deb = self.after(180, self._isik_gonder)

    def _temp_degisti(self, t, son):
        self._degisim(son, mode="white", temp=t * 100)

    def _bright_degisti(self, v, son):
        self._degisim(son, mode="white", bright=v)

    def _hue_degisti(self, t, son):
        self._degisim(son, mode="colour", h=t * 360)

    def _sat_degisti(self, v, son):
        self._degisim(son, mode="colour", s=v)

    def _v_degisti(self, v, son):
        self._degisim(son, mode="colour", v=v)

    def _hazir_renk(self, h):
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))
        hh, ss, _ = colorsys.rgb_to_hsv(r, g, b)
        self._degisim(True, mode="colour", h=hh * 360, s=ss * 100)

    # ---------- kurulum (QR) ekranı ----------
    def _kurulum_arayuz(self):
        f = self.setup
        tk.Label(f, text="Smart Life hesabını bağla", fg=FG, bg=PANEL,
                 font=(FONT, 11, "bold")).pack(pady=(14, 2))
        self.setup_neden = tk.Label(f, text="", fg=MUTED, bg=PANEL, font=(FONT, 8),
                                    wraplength=self.W - 40, justify="center")
        self.setup_neden.pack()
        tk.Label(f, text="Smart Life → Ben → Ayarlar (⚙) →\nHesap ve Güvenlik → Kullanıcı Kodu",
                 fg=MUTED, bg=PANEL, font=(FONT, 8), justify="center").pack(pady=(6, 0))
        self.code_entry = tk.Entry(f, bg=CARD, fg=FG, insertbackground=FG, relief="flat",
                                   font=(FONT, 11), justify="center", width=18)
        self.code_entry.pack(pady=(8, 6), ipady=5)
        self.code_entry.bind("<Return>", lambda e: self._qr_baslat())
        btn = tk.Label(f, text="QR oluştur", fg="white", bg=ACCENT, font=(FONT, 9, "bold"),
                       padx=14, pady=5, cursor="hand2")
        btn.pack()
        btn.bind("<Button-1>", lambda e: self._qr_baslat())
        self.qr_canvas = tk.Canvas(f, width=190, height=190, bg=PANEL, highlightthickness=0)
        self.qr_canvas.pack(pady=(12, 4))
        self.setup_msg = tk.Label(f, text="", fg=MUTED, bg=PANEL, font=(FONT, 8),
                                  wraplength=self.W - 40, justify="center")
        self.setup_msg.pack()

    def _kurulum_goster(self, neden=""):
        self.ctrl.pack_forget()
        self.setup.pack(fill="both", expand=True)
        self.dot.config(fg=MUTED)
        self.title_lbl.config(text="Kurulum")
        self.setup_neden.config(text=("Tuya projesinde ampul bulunamadı. " if neden else "") +
                                "Telefonla QR okutarak bağlanabilirsin.")
        self.code_entry.focus_set()

    def _setup_yaz(self, txt, renk=MUTED):
        self.setup_msg.config(text=txt, fg=renk)

    def _qr_baslat(self):
        code = self.code_entry.get().strip()
        if not code:
            self._setup_yaz("Önce kullanıcı kodunu gir", ERR)
            return
        self._setup_yaz("QR hazırlanıyor…")

        def is_():
            try:
                lc, token = qr_olustur(code)
            except Exception as e:
                self._ui(self._setup_yaz, f"Hata: {e}", ERR)
                return
            self._qr = (lc, token, code, time.time() + 120)
            self._ui(self._qr_ciz, f"tuyaSmart--qrLogin?token={token}")
            self._ui(self.after, 2000, self._qr_kontrol)

        self._gonder("qr", is_)

    def _qr_ciz(self, data):
        qr = qrcode.QRCode(border=2)
        qr.add_data(data)
        qr.make(fit=True)
        m = qr.get_matrix()
        n, size = len(m), 190
        cell = size // n
        off = (size - cell * n) // 2
        c = self.qr_canvas
        c.delete("all")
        c.create_rectangle(0, 0, size, size, fill="white", outline="")
        for y, row in enumerate(m):
            for x, v in enumerate(row):
                if v:
                    c.create_rectangle(off + x * cell, off + y * cell, off + (x + 1) * cell,
                                       off + (y + 1) * cell, fill="black", outline="")
        self._setup_yaz("Smart Life ana ekranında sağ üstteki tarayıcı ile okut ve onayla")

    def _qr_kontrol(self):
        if not self._qr:
            return
        lc, token, code, bitis = self._qr
        if time.time() > bitis:
            self._qr = None
            self.qr_canvas.delete("all")
            self._setup_yaz("QR'ın süresi doldu, yeniden oluştur", ERR)
            return

        def is_():
            try:
                auth = qr_sonuc(lc, token, code)
            except Exception:
                auth = None
            if auth is None:
                self._ui(self.after, 2000, self._qr_kontrol)
                return
            self._qr = None
            self.cfg["auth"] = auth
            for k in ("id", "key", "ip", "devices", "region"):
                self.cfg.pop(k, None)
            save_cfg(self.cfg)
            self.ampul.sifirla()
            self._ui(self._setup_yaz, "Giriş başarılı, ampul aranıyor…", OK)
            self._ui(self.after, 800, self._kontrol_goster)

        self._gonder("qrpoll", is_)

    # ---------- menü ----------
    def _menu_ac(self, e):
        m = self.menu
        m.delete(0, "end")
        m.add_checkbutton(label="Her zaman üstte", variable=self.topmost_var,
                          command=self._topmost_degistir)
        if self.ctrl.winfo_ismapped():
            m.add_command(label="Yeniden bağlan", command=self._yeniden_baglan)
            devs = self.cfg.get("devices") or []
            if len(devs) > 1:
                sub = tk.Menu(m, tearoff=0)
                for d in devs:
                    sub.add_command(label=d["name"], command=lambda d=d: self._cihaz_sec(d))
                m.add_cascade(label="Cihaz seç", menu=sub)
            m.add_command(label="Smart Life QR ile bağlan", command=self._hesap_sifirla)
        m.add_separator()
        m.add_command(label="Küçült", command=self._kucult)
        m.add_command(label="Kapat", command=self._kapat)
        m.tk_popup(e.x_root, e.y_root)

    def _topmost_degistir(self):
        v = self.topmost_var.get()
        self.attributes("-topmost", v)
        self.cfg["topmost"] = v
        save_cfg(self.cfg)

    def _yeniden_baglan(self):
        self.ampul.sifirla()
        self.dot.config(fg=MUTED)
        self._durum_yaz("Bağlanıyor…")
        self._gonder("init", self._baslat)

    def _cihaz_sec(self, d):
        self.cfg.update(id=d["id"], key=d["key"], name=d["name"], ip=None)
        self._yeniden_baglan()

    def _hesap_sifirla(self):
        for k in ("auth", "id", "key", "ip", "devices", "name", "region"):
            self.cfg.pop(k, None)
        save_cfg(self.cfg)
        self.ampul.sifirla()
        self._kurulum_goster()

    # ---------- pencere ----------
    def _drag_start(self, e):
        self._drag = (e.x_root - self.winfo_x(), e.y_root - self.winfo_y())

    def _drag_move(self, e):
        self.geometry(f"+{e.x_root - self._drag[0]}+{e.y_root - self._drag[1]}")

    def _kapat(self):
        self.cfg["x"], self.cfg["y"] = self.winfo_x(), self.winfo_y()
        save_cfg(self.cfg)
        self.destroy()


if __name__ == "__main__":
    Widget().mainloop()
