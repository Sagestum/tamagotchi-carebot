"""Daily e-mail report, sent when the Tamagotchi falls asleep for the night.

Configured on the settings page; environment variables (see .env.example)
are the defaults. Without a mail server and a recipient the report is
simply switched off.
"""
import os
import smtplib
import struct
import threading
import time
import zlib
from email.message import EmailMessage

from tama import LCD_H, LCD_W, TICK_HZ

SLEEP_AFTER = 20 * TICK_HZ      # asleep this long (emulated) = really asleep
WAKE_AFTER = 120 * TICK_HZ      # the sleep screen is hidden while a menu is open
MIN_GAP = 12 * 3600             # real seconds between two reports
COUNTED = {"Saubermachen": "cleaned", "Medizin geben": "healed", "Schimpfen": "scolded"}

LCD_BG, LCD_ON, LCD_OFF = (183, 196, 161), (32, 40, 28), (172, 185, 151)


def lcd_png(pixels, scale=12):
    """The 32x16 LCD as PNG bytes, drawn like the web UI does."""
    width, height = LCD_W * scale, LCD_H * scale
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            edge = x % scale in (0, scale - 1) or y % scale in (0, scale - 1)
            on = pixels[(y // scale) * LCD_W + x // scale]
            raw.extend(LCD_BG if edge else LCD_ON if on else LCD_OFF)

    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def smtp_from_env(env=os.environ):
    return {
        "host": env.get("SMTP_HOST", ""),
        "port": int(env.get("SMTP_PORT", "587")),
        "security": env.get("SMTP_SECURITY", "starttls").lower(),   # starttls | ssl | none
        "user": env.get("SMTP_USER", ""),
        "password": env.get("SMTP_PASSWORD", ""),
        "mail_from": env.get("MAIL_FROM", ""),
        "mail_to": env.get("MAIL_TO", ""),
    }


class DailyReport:
    def __init__(self, log, smtp=None, name=""):
        self.log = log
        self.name = name        # which pet, when there are several
        self.configure(smtp or smtp_from_env())

        self.asleep = False         # debounced
        self.flip_since = None      # tick since which the raw value disagrees
        self.prev_hearts = None
        self.picture = None         # last frame of the pet awake on its home screen
        self.last_sent = 0.0
        self.reset_counters()

    def configure(self, smtp):
        self.host = smtp["host"]
        self.port = smtp["port"]
        self.security = smtp["security"]
        self.user = smtp["user"]
        self.password = smtp["password"]
        self.mail_to = smtp["mail_to"]
        self.mail_from = smtp["mail_from"] or self.user or self.mail_to
        self.enabled = bool(self.host and self.mail_to)

    def reset_counters(self):
        self.stats = {"hunger": 0, "happy": 0, "cleaned": 0, "healed": 0,
                      "scolded": 0, "woke": None, "slept": None}

    # -- persistence -------------------------------------------------------

    def to_dict(self):
        return {"stats": self.stats, "asleep": self.asleep, "last_sent": self.last_sent,
                "picture": self.picture.hex() if self.picture else None}

    def from_dict(self, data):
        self.stats.update(data.get("stats", {}))
        self.asleep = data.get("asleep", False)
        self.last_sent = data.get("last_sent", 0.0)
        if data.get("picture"):
            self.picture = bytes.fromhex(data["picture"])

    # -- observation (called by the engine, about once per emulated second) --

    def count(self, msg):
        key = COUNTED.get(msg)
        if key:
            self.stats[key] += 1

    def observe(self, st, pixels, icons, ticks):
        if st["stage"] == 0 or st["dead"]:
            self.prev_hearts = None
            return

        hearts = (st["hunger"], st["happy"])
        if self.prev_hearts:
            self.stats["hunger"] += max(0, hearts[0] - self.prev_hearts[0])
            self.stats["happy"] += max(0, hearts[1] - self.prev_hearts[1])
        self.prev_hearts = hearts

        if not st["asleep"] and st["light"] and not any(icons[:7]):
            self.picture = bytes(pixels)

        if st["asleep"] == self.asleep:
            self.flip_since = None
        elif self.flip_since is None:
            self.flip_since = (ticks, st["clock"])
        elif ticks - self.flip_since[0] >= (SLEEP_AFTER if st["asleep"] else WAKE_AFTER):
            self.asleep = st["asleep"]
            when = self.flip_since[1]
            self.flip_since = None
            if self.asleep:
                self.stats["slept"] = when
                # Babies only nap; the report is for the night's sleep
                if st["stage"] >= 2 and time.time() - self.last_sent >= MIN_GAP:
                    self.send(st)
                    self.last_sent = time.time()
                    self.reset_counters()
            else:
                self.stats["woke"] = when

    # -- mail --------------------------------------------------------------

    def build(self, st):
        s = self.stats
        rows = [
            ("Aufgewacht", s["woke"] or "–"),
            ("Eingeschlafen", s["slept"] or "–"),
            ("Herzen aufgefüllt", "%d (Hunger %d, Glück %d)"
             % (s["hunger"] + s["happy"], s["hunger"], s["happy"])),
            ("Gewicht", "%d oz" % st["weight"]),
            ("Charakter", st["name"]),
            ("Pflegefehler", "%d, dazu %d verpasste Schimpf-Rufe" % (st["mistakes"], st["missed"])),
            ("Aktueller Stand", "Hunger %d/4, Glück %d/4" % (st["hunger"], st["happy"])),
        ]
        extra = [("%d× saubergemacht", s["cleaned"]), ("%d× Medizin", s["healed"]),
                 ("%d× geschimpft", s["scolded"])]
        extra = ", ".join(text % n for text, n in extra if n)
        if extra:
            rows.append(("Außerdem", extra))

        msg = EmailMessage()
        msg["Subject"] = "Tamagotchi-Tagesbericht" + (" " + self.name if self.name else "") + (
            ": schläft seit %s Uhr" % s["slept"] if s["slept"] else "")
        msg["From"] = self.mail_from
        msg["To"] = self.mail_to
        msg.set_content("\n".join("%s: %s" % row for row in rows) + "\n")
        html = "".join(
            '<tr><td style="padding:3px 16px 3px 0;color:#666">%s</td><td>%s</td></tr>' % row
            for row in rows)
        html = '<table style="font:15px sans-serif;border-collapse:collapse">%s</table>' % html
        if self.picture:
            html += ('<p style="font:13px sans-serif;color:#666">So sah es zuletzt wach aus:</p>'
                     '<img src="cid:lcd" width="384" height="192" alt="Tamagotchi-Display" '
                     'style="border-radius:8px">')
        msg.add_alternative("<html><body>%s</body></html>" % html, subtype="html")
        if self.picture:
            msg.get_payload()[1].add_related(lcd_png(self.picture), "image", "png", cid="<lcd>")
        return msg

    def send(self, st):
        if not self.enabled:
            return
        msg = self.build(dict(st))

        def run():
            try:
                cls = smtplib.SMTP_SSL if self.security == "ssl" else smtplib.SMTP
                with cls(self.host, self.port, timeout=30) as smtp:
                    if self.security == "starttls":
                        smtp.starttls()
                    if self.user:
                        smtp.login(self.user, self.password)
                    smtp.send_message(msg)
                self.log("Tagesbericht gesendet an " + self.mail_to)
            except Exception as e:  # report it in the UI log, the pet must go on
                self.log("Tagesbericht fehlgeschlagen: %s" % e)

        threading.Thread(target=run, daemon=True).start()
