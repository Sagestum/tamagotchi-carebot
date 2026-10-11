"""Daily e-mail report, sent when the Tamagotchi falls asleep for the night.

Configured on the settings page; environment variables (see .env.example)
are the defaults. Without a mail server and a recipient the report is
simply switched off.

With several pets the reports can be gathered into one mail a day: each pet then hands its
report to the server (hand_over) instead of sending it, and the server sends them together.
"""
import os
import smtplib
import struct
import threading
import time
import zlib
from email.message import EmailMessage
from html import escape

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
        # one mail a day for all pets, at the latest at this time of day
        "digest": env.get("MAIL_DIGEST", "").lower() in ("1", "true", "yes", "on"),
        "digest_at": env.get("MAIL_DIGEST_AT", "23:00"),
    }


def compose(sections, mail_from, mail_to):
    """The mail for one report or, gathered, for several. A section is what
    DailyReport.section() returns."""
    one = len(sections) == 1
    msg = EmailMessage()
    if one:
        name, slept = sections[0]["name"], sections[0]["slept"]
        msg["Subject"] = "Tamagotchi-Tagesbericht" + (" " + name if name else "") + (
            ": schläft seit %s Uhr" % slept if slept else "")
    else:
        msg["Subject"] = "Tamagotchi-Tagesbericht: %d Tiere" % len(sections)
    msg["From"] = mail_from
    msg["To"] = mail_to
    text, html, pictures = [], [], []
    for n, sec in enumerate(sections):
        title = (sec["name"] or "Tamagotchi") + (
            " – schläft seit %s Uhr" % sec["slept"] if sec["slept"] else "")
        rows = [tuple(row) for row in sec["rows"]]
        text.append(("" if one else title + "\n") + "\n".join("%s: %s" % row for row in rows) + "\n")
        part = "".join(
            '<tr><td style="padding:3px 16px 3px 0;color:#666">%s</td><td>%s</td></tr>'
            % (escape(row[0]), escape(str(row[1]))) for row in rows)
        part = '<table style="font:15px sans-serif;border-collapse:collapse">%s</table>' % part
        if not one:
            part = '<h2 style="font:bold 17px sans-serif;margin:26px 0 8px">%s</h2>' % escape(title) + part
        if sec.get("picture"):
            part += ('<p style="font:13px sans-serif;color:#666">So sah es zuletzt wach aus:</p>'
                     '<img src="cid:lcd%d" width="384" height="192" alt="Tamagotchi-Display" '
                     'style="border-radius:8px">' % n)
            pictures.append((n, sec["picture"]))
        html.append(part)
    msg.set_content("\n".join(text))
    msg.add_alternative("<html><body>%s</body></html>" % "".join(html), subtype="html")
    for n, picture in pictures:
        msg.get_payload()[1].add_related(lcd_png(picture), "image", "png", cid="<lcd%d>" % n)
    return msg


def deliver(smtp, msg, done):
    """Send in the background; done(error or None) is called afterwards."""
    def run():
        try:
            cls = smtplib.SMTP_SSL if smtp["security"] == "ssl" else smtplib.SMTP
            with cls(smtp["host"], smtp["port"], timeout=30) as server:
                if smtp["security"] == "starttls":
                    server.starttls()
                if smtp["user"]:
                    server.login(smtp["user"], smtp["password"])
                server.send_message(msg)
            done(None)
        except Exception as e:  # report it in the UI log, the pet must go on
            done(e)

    threading.Thread(target=run, daemon=True).start()


class DailyReport:
    def __init__(self, log, smtp=None, name=""):
        self.log = log
        self.name = name        # which pet, when there are several
        self.unit = "oz"        # of the weight
        self.hand_over = None   # takes a report for the gathered mail (set by the worker)
        self.rows = None        # (status, stats) -> rows, for a device that is no Tamagotchi
        self.configure(smtp or smtp_from_env())

        self.asleep = False         # debounced
        self.flip_since = None      # tick since which the raw value disagrees
        self.prev_hearts = None
        self.picture = None         # last frame of the pet awake on its home screen
        self.last_sent = 0.0
        self.reset_counters()

    def configure(self, smtp):
        self.smtp = smtp
        self.mail_to = smtp["mail_to"]
        self.mail_from = smtp["mail_from"] or smtp["user"] or self.mail_to
        self.enabled = bool(smtp["host"] and self.mail_to)
        self.digest = bool(smtp.get("digest"))

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

        if not st["asleep"] and st["light"] and not any(icons[:7]) and not st.get("saver"):
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
                if (st["stage"] >= 2 or self.rows) and time.time() - self.last_sent >= MIN_GAP:
                    self.send(st)
                    self.last_sent = time.time()
                    self.reset_counters()
            else:
                self.stats["woke"] = when

    # -- mail --------------------------------------------------------------

    def section(self, st):
        """The report as data: for compose(), and to hand over for the gathered mail."""
        s = self.stats
        rows = self.rows(st, s) if self.rows else [
            ("Aufgewacht", s["woke"] or "–"),
            ("Eingeschlafen", s["slept"] or "–"),
            ("Herzen aufgefüllt", "%d (Hunger %d, Glück %d)"
             % (s["hunger"] + s["happy"], s["hunger"], s["happy"])),
            ("Angel Power" if self.unit == "AP" else "Gewicht", "%d %s" % (st["weight"], self.unit)),
            ("Charakter", st["name"]),
            ("Pflegefehler", "%d, dazu %d verpasste Schimpf-Rufe" % (st["mistakes"], st["missed"])),
            ("Aktueller Stand", "Hunger %d/4, Glück %d/4" % (st["hunger"], st["happy"])),
        ]
        extra = [("%d× saubergemacht", s["cleaned"]), ("%d× Medizin", s["healed"]),
                 ("%d× geschimpft", s["scolded"])]
        extra = ", ".join(text % n for text, n in extra if n)
        if extra and not self.rows:
            rows.append(("Außerdem", extra))

        return {"name": self.name, "slept": s["slept"], "rows": rows, "picture": self.picture,
                "at": time.time()}

    def send(self, st, direct=False):
        """The report of this pet: sent, or handed over when the reports are gathered
        (direct: sent in any case, for the button in the UI)."""
        if not self.enabled:
            return
        section = self.section(dict(st))
        if self.digest and self.hand_over and not direct:
            self.hand_over(section)
            self.log("Tagesbericht für die Sammel-Mail vorgemerkt")
            return

        def done(error):
            if error:
                self.log("Tagesbericht fehlgeschlagen: %s" % error)
            else:
                self.log("Tagesbericht gesendet an " + self.mail_to)

        deliver(self.smtp, compose([section], self.mail_from, self.mail_to), done)
