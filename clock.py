"""
ඔරලෝසු ඇප් එක (Windows 11)
- Analog + Digital ඔරලෝසු (තත්පර සහිතව)
- Internet (NTP) වෙලාවට sync වීම
- Alarm කණ්ඩායම් 3ක් (A, B, C): වෙලාවන්, ශබ්දය, volume ඔක්කොම වෙනස් කරන්න පුළුවන්
- සෑම Alarm එකක්ම AM සහ PM දෙකේදීම ඇහෙනවා
Python 3.8+ පමණයි. අමතර ඉන්ස්ටෝල් කිසිවක් ඕන නැහැ.
"""
import json
import math
import os
import socket
import struct
import sys
import tempfile
import threading
import time
import tkinter as tk
import wave
from array import array
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

try:
    import winsound
except ImportError:  # Windows නොවන පද්ධති වලදී
    winsound = None

# ---------------------------------------------------------------- සැකසුම්
BASE = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
SETTINGS_FILE = os.path.join(BASE, "clock_settings.json")
TEMP_WAV = os.path.join(tempfile.gettempdir(), "sinhala_clock_alarm.wav")
RATE = 22050
NTP_SERVERS = ["time.windows.com", "pool.ntp.org", "time.google.com"]
SYNC_EVERY = 15 * 60  # තත්පර 900 කට වරක් නැවත sync වෙනවා

BG, FG, ACCENT, PANEL, RED = "#1e1e2e", "#cdd6f4", "#89b4fa", "#313244", "#f38ba8"
UI_FONT = "Nirmala UI"  # සිංහල අකුරු හොඳින් පෙනෙන Windows font එකක්
NUM_FONT = "Segoe UI"
CUSTOM_LABEL = "📁 ෆයිල් එකක් තෝරන්න (.wav)..."


# ---------------------------------------------------------------- ශබ්ද සෑදීම
def tone(freq, dur, amp=0.8, decay=True):
    n = int(RATE * dur)
    out = array("h")
    for i in range(n):
        t = i / RATE
        env = min(1.0, i / (RATE * 0.01), (n - i) / (RATE * 0.02))
        if decay:
            env *= math.exp(-3 * t / dur)
        out.append(int(32767 * amp * env * math.sin(2 * math.pi * freq * t)))
    return out


def silence(dur):
    return array("h", [0]) * int(RATE * dur)


def _simple_beeps():
    a = array("h")
    for _ in range(3):
        a += tone(880, 0.25, decay=False) + silence(0.15)
    return a


def _chime():
    a = array("h")
    for f in (1319, 1047, 880):
        a += tone(f, 0.7)
    return a


def _soft_bell():
    return tone(660, 1.0) + tone(880, 1.3)


def _digital():
    a = array("h")
    for _ in range(2):
        for _ in range(4):
            a += tone(1000, 0.1, decay=False) + tone(1400, 0.1, decay=False)
        a += silence(0.3)
    return a


def _rising():
    a = array("h")
    for f in (523, 659, 784, 1047):
        a += tone(f, 0.3)
    return a


BUILTIN = {
    "සරල බීප්": _simple_beeps,
    "සීනුව": _chime,
    "මෘදු සීනුව": _soft_bell,
    "ඩිජිටල් ඇලාම්": _digital,
    "ඉහළ යන සුර": _rising,
}
_cache = {}


def load_wav_samples(path):
    with wave.open(path, "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError("16-bit PCM WAV ෆයිල් එකක් විතරයි පාවිච්චි කරන්න පුළුවන්.")
        ch, rate = w.getnchannels(), w.getframerate()
        data = array("h")
        data.frombytes(w.readframes(w.getnframes()))
    if sys.byteorder == "big":
        data.byteswap()
    return data, ch, rate


def get_samples(spec):
    if spec.startswith("file:"):
        return load_wav_samples(spec[5:])
    if spec not in _cache:
        _cache[spec] = BUILTIN.get(spec, _chime)()
    return _cache[spec], 1, RATE


def write_wav(path, samples, ch, rate):
    if sys.byteorder == "big":
        samples = array("h", samples)
        samples.byteswap()
    with wave.open(path, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())


def stop_sound():
    if winsound:
        winsound.PlaySound(None, winsound.SND_PURGE)


def play_sound(root, spec, vol):
    """spec: built-in නමක් හෝ 'file:<path>'. vol: 0-100"""
    try:
        samples, ch, rate = get_samples(spec)
        v = (vol / 100) ** 2  # ස්වභාවික volume වක්‍රයක්
        scaled = array("h", (int(x * v) for x in samples))
        if winsound:
            stop_sound()
            write_wav(TEMP_WAV, scaled, ch, rate)
            winsound.PlaySound(TEMP_WAV, winsound.SND_FILENAME | winsound.SND_ASYNC)
        else:
            root.bell()
    except Exception as e:
        print("ශබ්දය වාදනය කළ නොහැකි විය:", e)
        root.bell()


# ---------------------------------------------------------------- Internet වෙලාව (NTP)
def ntp_offset():
    """PC වෙලාව සහ Internet වෙලාව අතර වෙනස (තත්පර) ආපසු දෙනවා."""
    for server in NTP_SERVERS:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.settimeout(3)
                t0 = time.time()
                s.sendto(b"\x1b" + 47 * b"\0", (server, 123))
                data, _ = s.recvfrom(48)
                t1 = time.time()
            if len(data) < 48:
                continue
            secs, frac = struct.unpack("!II", data[40:48])
            server_time = secs - 2208988800 + frac / 2 ** 32
            return server_time - (t0 + t1) / 2, server
        except Exception:
            continue
    return None, None


class TimeSync:
    def __init__(self):
        self.offset = 0.0
        self.status = "Internet වෙලාව සමග sync වෙමින්..."
        self.wake = threading.Event()

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            self.status = "Internet වෙලාව සමග sync වෙමින්..."
            off, srv = ntp_offset()
            if off is None:
                self.status = "⚠ Internet වෙලාව ගන්න බැරි වුණා. PC එකේ වෙලාව පාවිච්චි කරනවා."
                wait = 60
            else:
                self.offset = off
                self.status = f"✔ Internet වෙලාවට sync වුණා ({srv}) • PC එකේ වෙනස: {off:+.2f} තත්පර"
                wait = SYNC_EVERY
            self.wake.wait(wait)
            self.wake.clear()

    def now(self):
        return datetime.fromtimestamp(time.time() + self.offset)


# ---------------------------------------------------------------- Settings
def default_settings():
    def mk(hours, minute):
        return [{"h": h, "m": minute, "vol": 80, "on": True} for h in hours]

    return {
        "use_24h": False,
        "groups": {
            "A": {"title": "කණ්ඩායම A: 1:30 • 5:30 • 9:30", "sound": "ඉහළ යන සුර",
                  "alarms": mk([1, 5, 9], 30)},
            "B": {"title": "කණ්ඩායම B: 2:30 • 3:30 • 4:30 • 6:30 • 7:30 • 8:30 • 10:30 • 11:30 • 12:30",
                  "sound": "මෘදු සීනුව", "alarms": mk([2, 3, 4, 6, 7, 8, 10, 11, 12], 30)},
            "C": {"title": "කණ්ඩායම C: පැය ගණන් (1:00 සිට 12:00 දක්වා)", "sound": "සීනුව",
                  "alarms": mk(range(1, 13), 0)},
        },
    }


def load_settings():
    s = default_settings()
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        s["use_24h"] = bool(data.get("use_24h", False))
        for k in s["groups"]:
            g = data.get("groups", {}).get(k)
            if g:
                s["groups"][k]["sound"] = g.get("sound", s["groups"][k]["sound"])
                s["groups"][k]["alarms"] = [
                    {"h": int(a["h"]), "m": int(a["m"]), "vol": int(a.get("vol", 80)),
                     "on": bool(a.get("on", True))} for a in g.get("alarms", [])
                ]
    except Exception:
        pass
    return s


def sound_display(spec):
    return "📁 " + os.path.basename(spec[5:]) if spec.startswith("file:") else spec


def fmt_hm(h, m):
    return f"{h}:{m:02d}"


# ---------------------------------------------------------------- ප්‍රධාන ඇප් එක
class App:
    def __init__(self, root):
        self.root = root
        root.title("ඔරලෝසුව")
        root.geometry("540x780")
        root.minsize(500, 720)
        root.configure(bg=BG)
        self.settings = load_settings()
        self.sync = TimeSync()
        self.sync.start()
        self.banner_until = 0
        self.ui = {}

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL, foreground=FG, padding=(14, 6),
                        font=(UI_FONT, 10))
        style.map("TNotebook.Tab", background=[("selected", ACCENT)], foreground=[("selected", BG)])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG,
                        rowheight=26, font=(UI_FONT, 11), borderwidth=0)
        style.configure("Treeview.Heading", background=BG, foreground=ACCENT, font=(UI_FONT, 10, "bold"))
        style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", BG)])
        style.configure("TCombobox", fieldbackground=PANEL, background=PANEL, foreground=FG)

        nb = ttk.Notebook(root)
        nb.pack(fill="both", expand=True, padx=6, pady=6)
        clock_tab = tk.Frame(nb, bg=BG)
        nb.add(clock_tab, text="ඔරලෝසුව")
        self.build_clock_tab(clock_tab)
        for key in "ABC":
            tab = tk.Frame(nb, bg=BG)
            nb.add(tab, text=f"Alarm {key}")
            self.build_group_tab(tab, key)

        now = self.sync.now()
        self.last_key = self.minute_key(now)  # ඇරඹූ විනාඩියේ Alarm එක වහාම නාදවීම වළක්වයි
        self.refresh_next(now)
        self.tick()
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------ උපකරණ
    def button(self, parent, text, cmd, **kw):
        return tk.Button(parent, text=text, command=cmd, bg=PANEL, fg=FG, activebackground="#45475a",
                         activeforeground=FG, relief="flat", padx=10, pady=5, font=(UI_FONT, 10), **kw)

    def label(self, parent, text, size=11, color=FG, bold=False, **kw):
        return tk.Label(parent, text=text, bg=BG, fg=color, font=(UI_FONT, size, "bold" if bold else "normal"), **kw)

    @staticmethod
    def minute_key(now):
        return (now.year, now.month, now.day, now.hour, now.minute)

    def save(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print("Settings සේව් කළ නොහැකි විය:", e)

    def on_close(self):
        self.save()
        stop_sound()
        self.root.destroy()

    # ------------------------------------------------ ඔරලෝසු tab එක
    def build_clock_tab(self, parent):
        self.cx = self.cy = 160
        self.canvas = tk.Canvas(parent, width=320, height=320, bg=BG, highlightthickness=0)
        self.canvas.pack(pady=(14, 4))
        c, cx, cy = self.canvas, self.cx, self.cy
        c.create_oval(cx - 145, cy - 145, cx + 145, cy + 145, outline=ACCENT, width=3)
        for i in range(60):
            ang = math.radians(i * 6 - 90)
            r1 = 128 if i % 5 == 0 else 135
            c.create_line(cx + r1 * math.cos(ang), cy + r1 * math.sin(ang),
                          cx + 142 * math.cos(ang), cy + 142 * math.sin(ang),
                          fill=FG if i % 5 == 0 else "#6c7086", width=3 if i % 5 == 0 else 1)
        for n in range(1, 13):
            ang = math.radians(n * 30 - 90)
            c.create_text(cx + 108 * math.cos(ang), cy + 108 * math.sin(ang), text=str(n),
                          fill=FG, font=(NUM_FONT, 16, "bold"))

        self.time_lbl = tk.Label(parent, bg=BG, fg=ACCENT, font=(NUM_FONT, 40, "bold"))
        self.time_lbl.pack()
        self.date_lbl = tk.Label(parent, bg=BG, fg=FG, font=(NUM_FONT, 14))
        self.date_lbl.pack()

        row = tk.Frame(parent, bg=BG)
        row.pack(pady=10)
        self.button(row, "12 / 24 පැය මාරු කරන්න", self.toggle_format).pack(side="left", padx=4)
        self.button(row, "දැන්ම sync කරන්න", lambda: self.sync.wake.set()).pack(side="left", padx=4)

        self.sync_lbl = self.label(parent, "", size=9, color="#a6adc8", wraplength=480, justify="center")
        self.sync_lbl.pack(pady=2)
        self.next_lbl = self.label(parent, "", size=11, color=FG, wraplength=480, justify="center")
        self.next_lbl.pack(pady=(8, 2))
        self.banner_lbl = self.label(parent, "", size=14, color=RED, bold=True, wraplength=480)
        self.banner_lbl.pack(pady=4)
        self.button(parent, "🔇 ශබ්දය නවත්වන්න", self.stop_alarm).pack(pady=4)

    def toggle_format(self):
        self.settings["use_24h"] = not self.settings["use_24h"]
        self.save()

    def stop_alarm(self):
        stop_sound()
        self.banner_lbl.config(text="")
        self.banner_until = 0

    def draw_hands(self, now):
        c, cx, cy = self.canvas, self.cx, self.cy
        c.delete("hands")
        sec = now.second + now.microsecond / 1e6
        minute = now.minute + sec / 60
        hour = (now.hour % 12) + minute / 60
        for angle, length, width, color in (
            (hour * 30, 80, 7, ACCENT),
            (minute * 6, 115, 4, FG),
            (sec * 6, 128, 2, RED),
        ):
            rad = math.radians(angle - 90)
            c.create_line(cx, cy, cx + length * math.cos(rad), cy + length * math.sin(rad),
                          width=width, fill=color, capstyle="round", tags="hands")
        c.create_oval(cx - 6, cy - 6, cx + 6, cy + 6, fill=RED, outline="", tags="hands")

    def refresh_next(self, now):
        cur = now.hour * 60 + now.minute
        best = None
        for g in self.settings["groups"].values():
            for a in g["alarms"]:
                if not a["on"]:
                    continue
                base = (a["h"] % 12) * 60 + a["m"]
                for cand in (base, base + 720):
                    d = (cand - cur) % 1440 or 1440
                    if best is None or d < best[0]:
                        best = (d, a)
        if best is None:
            self.next_lbl.config(text="සක්‍රිය Alarm කිසිවක් නැහැ")
            return
        d, a = best
        h, m = divmod(d, 60)
        when = f"{h} පැය {m} මිනිත්තුවකින්" if h else f"මිනිත්තු {m}කින්"
        self.next_lbl.config(text=f"ඊළඟ Alarm එක: {fmt_hm(a['h'], a['m'])} ({when})")

    # ------------------------------------------------ ප්‍රධාන tick
    def tick(self):
        now = self.sync.now()
        fmt = "%H:%M:%S" if self.settings["use_24h"] else "%I:%M:%S %p"
        self.time_lbl.config(text=now.strftime(fmt))
        self.date_lbl.config(text=now.strftime("%A, %d %B %Y"))
        self.draw_hands(now)
        if self.sync_lbl.cget("text") != self.sync.status:
            self.sync_lbl.config(text=self.sync.status)

        key = self.minute_key(now)
        if key != self.last_key:
            self.last_key = key
            self.check_alarms(now)
            self.refresh_next(now)
        if self.banner_until and time.time() > self.banner_until:
            self.banner_lbl.config(text="")
            self.banner_until = 0
        self.root.after(100, self.tick)

    def check_alarms(self, now):
        h12 = now.hour % 12 or 12
        matches = []
        for k, g in self.settings["groups"].items():
            for a in g["alarms"]:
                if a["on"] and a["h"] == h12 and a["m"] == now.minute:
                    matches.append((k, g, a))
        if matches:
            k, g, a = matches[0]
            play_sound(self.root, g["sound"], a["vol"])
            self.banner_lbl.config(text=f"🔔 {fmt_hm(a['h'], a['m'])}  (කණ්ඩායම {k})")
            self.banner_until = time.time() + 30

    # ------------------------------------------------ Alarm කණ්ඩායම් tab
    def build_group_tab(self, parent, key):
        g = self.settings["groups"][key]
        self.label(parent, g["title"], size=11, color=ACCENT, bold=True, wraplength=490).pack(pady=(12, 6))

        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=14, pady=4)
        self.label(row, "Alarm ශබ්දය:").pack(side="left")
        combo = ttk.Combobox(row, state="readonly", values=list(BUILTIN) + [CUSTOM_LABEL], width=30,
                             font=(UI_FONT, 10))
        combo.set(sound_display(g["sound"]))
        combo.pack(side="left", padx=8)
        combo.bind("<<ComboboxSelected>>", lambda e, k=key: self.on_sound_change(k))

        tree = ttk.Treeview(parent, columns=("t", "v", "o"), show="headings", height=11, selectmode="browse")
        for col, text, w in (("t", "වෙලාව", 140), ("v", "Volume", 140), ("o", "සක්‍රිය", 100)):
            tree.heading(col, text=text)
            tree.column(col, width=w, anchor="center")
        tree.pack(fill="both", expand=True, padx=14, pady=8)

        btns = tk.Frame(parent, bg=BG)
        btns.pack(pady=2)
        items = (("➕ එකතු කරන්න", lambda k=key: self.alarm_dialog(k)),
                 ("✏ වෙනස් කරන්න", lambda k=key: self.edit_selected(k)),
                 ("🗑 මකන්න", lambda k=key: self.delete_selected(k)),
                 ("⏻ සක්‍රිය/අක්‍රිය", lambda k=key: self.toggle_selected(k)),
                 ("▶ ශබ්දය අහන්න", lambda k=key: self.test_selected(k)))
        for i, (text, cmd) in enumerate(items):
            self.button(btns, text, cmd).grid(row=i // 3, column=i % 3, padx=4, pady=3, sticky="ew")

        bulk = tk.Frame(parent, bg=BG)
        bulk.pack(pady=(10, 12))
        self.label(bulk, "සියලුම Alarm වල volume:").pack(side="left")
        scale = tk.Scale(bulk, from_=0, to=100, orient="horizontal", length=160, bg=BG, fg=FG,
                         highlightthickness=0, troughcolor=PANEL)
        scale.set(80)
        scale.pack(side="left", padx=6)
        self.button(bulk, "යොදන්න", lambda k=key: self.apply_all_volume(k)).pack(side="left")

        self.ui[key] = {"tree": tree, "combo": combo, "bulk": scale}
        self.refresh_tree(key)

    def refresh_tree(self, key):
        tree = self.ui[key]["tree"]
        tree.delete(*tree.get_children())
        for i, a in enumerate(self.settings["groups"][key]["alarms"]):
            tree.insert("", "end", iid=str(i),
                        values=(fmt_hm(a["h"], a["m"]) + "  (AM/PM)", f"{a['vol']}%", "✔" if a["on"] else "✘"))

    def selected(self, key):
        sel = self.ui[key]["tree"].selection()
        if not sel:
            messagebox.showinfo("තෝරන්න", "මුලින් ලිස්ට් එකෙන් Alarm එකක් තෝරන්න.")
            return None
        return int(sel[0])

    def changed(self, key):
        self.settings["groups"][key]["alarms"].sort(key=lambda a: (a["h"], a["m"]))
        self.refresh_tree(key)
        self.refresh_next(self.sync.now())
        self.save()

    def edit_selected(self, key):
        i = self.selected(key)
        if i is not None:
            self.alarm_dialog(key, i)

    def delete_selected(self, key):
        i = self.selected(key)
        if i is not None and messagebox.askyesno("මකන්නද?", "මේ Alarm එක මකන්නද?"):
            del self.settings["groups"][key]["alarms"][i]
            self.changed(key)

    def toggle_selected(self, key):
        i = self.selected(key)
        if i is not None:
            a = self.settings["groups"][key]["alarms"][i]
            a["on"] = not a["on"]
            self.changed(key)
            self.ui[key]["tree"].selection_set(str(i))

    def test_selected(self, key):
        i = self.selected(key)
        if i is not None:
            g = self.settings["groups"][key]
            play_sound(self.root, g["sound"], g["alarms"][i]["vol"])

    def apply_all_volume(self, key):
        v = int(self.ui[key]["bulk"].get())
        for a in self.settings["groups"][key]["alarms"]:
            a["vol"] = v
        self.changed(key)

    def on_sound_change(self, key):
        g = self.settings["groups"][key]
        combo = self.ui[key]["combo"]
        sel = combo.get()
        if sel == CUSTOM_LABEL:
            path = filedialog.askopenfilename(title="WAV ෆයිල් එකක් තෝරන්න", filetypes=[("WAV ශබ්ද ෆයිල්", "*.wav")])
            if path:
                try:
                    load_wav_samples(path)
                    g["sound"] = "file:" + path
                except Exception as e:
                    messagebox.showerror("ෆයිල් එක පාවිච්චි කළ නොහැක", str(e))
        else:
            g["sound"] = sel
        combo.set(sound_display(g["sound"]))
        self.save()

    def alarm_dialog(self, key, index=None):
        g = self.settings["groups"][key]
        cur = g["alarms"][index] if index is not None else {"h": 1, "m": 0, "vol": 80, "on": True}
        win = tk.Toplevel(self.root)
        win.title("Alarm එක")
        win.configure(bg=BG)
        win.transient(self.root)
        win.resizable(False, False)
        hv, mv, vv = tk.StringVar(value=str(cur["h"])), tk.StringVar(value=f"{cur['m']:02d}"), tk.IntVar(value=cur["vol"])

        frm = tk.Frame(win, bg=BG)
        frm.pack(padx=22, pady=16)
        self.label(frm, "පැය (1-12):").grid(row=0, column=0, sticky="w", pady=6)
        tk.Spinbox(frm, from_=1, to=12, width=5, textvariable=hv, wrap=True, justify="center",
                   font=(NUM_FONT, 12)).grid(row=0, column=1, padx=8)
        self.label(frm, "මිනිත්තු (0-59):").grid(row=1, column=0, sticky="w", pady=6)
        tk.Spinbox(frm, from_=0, to=59, width=5, textvariable=mv, wrap=True, justify="center",
                   format="%02.0f", font=(NUM_FONT, 12)).grid(row=1, column=1, padx=8)
        self.label(frm, "Volume:").grid(row=2, column=0, sticky="w", pady=6)
        tk.Scale(frm, from_=0, to=100, orient="horizontal", variable=vv, length=200, bg=BG, fg=FG,
                 highlightthickness=0, troughcolor=PANEL).grid(row=2, column=1, padx=8)
        self.label(frm, "මේ වෙලාව AM සහ PM දෙකේදීම නාද වෙනවා.", size=9, color="#a6adc8").grid(
            row=3, column=0, columnspan=2, pady=(6, 0))

        def read():
            try:
                h, m = int(hv.get()), int(mv.get())
                if not (1 <= h <= 12 and 0 <= m <= 59):
                    raise ValueError
            except ValueError:
                messagebox.showerror("වැරදියි", "පැය 1-12 අතර සහ මිනිත්තු 0-59 අතර අගයන් දෙන්න.", parent=win)
                return None
            return h, m

        def do_save():
            hm = read()
            if not hm:
                return
            h, m = hm
            for j, a in enumerate(g["alarms"]):
                if j != index and a["h"] == h and a["m"] == m:
                    messagebox.showerror("දැනටමත් තියෙනවා", "මේ වෙලාව මේ කණ්ඩායමේ දැනටමත් තියෙනවා.", parent=win)
                    return
            new = {"h": h, "m": m, "vol": int(vv.get()), "on": cur["on"]}
            if index is None:
                g["alarms"].append(new)
            else:
                g["alarms"][index] = new
            self.changed(key)
            win.destroy()

        row = tk.Frame(win, bg=BG)
        row.pack(pady=(0, 16))
        self.button(row, "▶ අහන්න", lambda: play_sound(self.root, g["sound"], int(vv.get()))).pack(side="left", padx=4)
        self.button(row, "සේව් කරන්න", do_save).pack(side="left", padx=4)
        self.button(row, "අවලංගු", win.destroy).pack(side="left", padx=4)
        win.grab_set()


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
