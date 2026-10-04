# Tamagotchi P1 im Browser, mit Care-Bot

Das Original-Tamagotchi von 1996/97 läuft hier als emulierte ROM auf einem Server und wird im
Browser angezeigt. Ein Care-Bot drückt die drei Tasten, wenn das Tier etwas braucht, und kann
gezielt einen bestimmten Charakter großziehen.

![Die Oberfläche](docs/img/oberflaeche.jpg)

Die Emulation übernimmt [TamaLIB](https://github.com/jcrona/tamalib) von Jean-Christophe Rona.
Darum herum liegen eine dünne C-Hülle, ein Python-Server ohne weitere Abhängigkeiten und zwei
HTML-Seiten.

## Die ROM gehört nicht dazu

Die ROM ist urheberrechtlich geschützt und liegt nicht in diesem Repository. Gebraucht wird die
Datei `tama.b` aus dem MAME-Romset `tama`:

| | |
|---|---|
| Größe | 12 288 Bytes |
| SHA-1 | `4b4979cf92dc9d2fb6d7295a38f209f3da144f72` |
| CRC32 | `5c864cb1` |

Fehlt die ROM beim Start, zeigt der Server statt des Tamagotchis die Seite „Optionen“ und fragt
danach: Man lädt `tama.b` (oder MAMEs `tama.zip`) im Browser hoch oder nennt den Pfad, unter dem
sie auf dem Server liegt. Angenommen wird die Datei nur, wenn die Prüfsumme passt. Gespeichert
wird sie als `tama.b` neben dem Spielstand. Wer sie selbst hinlegen will: dorthin oder nach
`tama/tama.b`, oder `--rom` angeben.

![Erster Start ohne ROM](docs/img/optionen.jpg)

## Starten

```bash
python3 server.py            # baut libtama.so bei Bedarf, dann http://127.0.0.1:8137
```

Benötigt `gcc`, `make` und `python3`. Strg+C beendet und speichert den Spielstand in
`tama_state.json`. Mit Docker: `docker compose up -d --build`; Spielstand, ROM und
Einstellungen liegen dann im Volume unter `/data`. Die Compose-Datei veröffentlicht
keinen Port und erwartet ein externes Netz `httpd` für einen Reverse-Proxy; das ist an die
eigene Umgebung anzupassen. Die Oberfläche hat keine Anmeldung und gehört nicht ungeschützt ins
Internet.

Das Tier lebt im Server-Prozess und läuft weiter, wenn kein Browser offen ist. Das Tempo lässt
sich bis etwa 2600-fach hochdrehen.

Optional schickt der Server abends einen Tagesbericht per E-Mail. Der Mailserver wird auf der
Seite „Optionen“ (`/settings`) eingetragen und in `settings.json` neben dem Spielstand
gespeichert, das Passwort unverschlüsselt. Umgebungsvariablen (`.env.example`) dienen als
Vorgabe.

## Der Care-Bot

Der Bot liest Hunger, Glück, Häufchen und Krankheit aus dem RAM und dem Display und bedient dann
das Menü wie ein Mensch: A wählt das Icon, B bestätigt, C bricht ab. Er stellt außerdem die Uhr
des Geräts nach der Systemzeit.

Auf der Unterseite `/bot` lässt sich ein Ziel wählen. Der Bot macht dann genau die Fehler, die
für diesen Charakter nötig sind, und pflegt sonst fehlerfrei.

![Der Wachstumsbaum mit Ziel](docs/img/wachstumsbaum.jpg)

## Was den Charakter bestimmt

Die ROM zählt zwei Dinge, beide ab der Kind-Stufe, beide nur aufwärts bis 15 und für das ganze
Leben:

- **Pflegefehler** (RAM `0x42`): Ein Ruf wegen leerem Hunger oder leerem Glück bleibt etwa
  15 Minuten unbeantwortet, oder das Licht bleibt beim Schlafen 65 Minuten an.
- **Verpasste Schimpf-Rufe** (RAM `0x51`): Das Tier ruft, obwohl nichts fehlt, und wird etwa
  15 Minuten lang nicht geschimpft.

Die Disziplin-Anzeige im Status-Bild (RAM `0x43`) geht in die Entscheidung nicht ein.

| Verwandlung | Pflegefehler | verpasste Schimpf-Rufe | wird zu |
|---|---|---|---|
| Marutchi (Kind) | 0–2 | egal | Tamatchi |
| | ab 3 | egal | Kuchitamatchi |
| Tamatchi | 0–2 | 0 | Mametchi |
| | 0–2 | 1 | Ginjirotchi |
| | 0–2 | ab 2 | Maskutchi |
| | ab 3 | 0–1 | Kuchipatchi |
| | ab 3 | 2–3 | Nyorotchi |
| | ab 3 | ab 4 | Tarakotchi |
| Kuchitamatchi | egal | 0–1 | Kuchipatchi |
| | egal | 2 | Nyorotchi |
| | egal | ab 3 | Tarakotchi |

Hat schon das Kind drei oder mehr Schimpf-Rufe verpasst, entsteht eine zweite Art Teenager mit
anderen Grenzen (RAM `0x50`):

| Verwandlung | Pflegefehler | verpasste Schimpf-Rufe | wird zu |
|---|---|---|---|
| Tamatchi, zweite Art | 0–3 | ab 2 | Maskutchi, vier Tage später Oyajitchi |
| | ab 4 | bis 7 | Nyorotchi |
| | ab 4 | ab 8 | Tarakotchi |
| Kuchitamatchi, zweite Art | egal | bis 5 | Nyorotchi |
| | egal | ab 6 | Tarakotchi |

Die Geheimfigur Oyajitchi entsteht nur aus diesem Maskutchi. Ob danach geschimpft wird, ändert
daran nichts.

Diese Tabellen stammen nicht aus dem Netz, sondern aus der ROM: Kurz vor jeder Verwandlung
wurden beide Zähler im emulierten RAM auf alle 16 × 16 Kombinationen gesetzt und das Ergebnis
ausgelesen. Die Skripte dazu liegen in [`lab/`](lab/). Getestet ist nur dieser eine ROM-Dump;
andere Fassungen und die Neuauflagen können anders rechnen.

| | | | |
|---|---|---|---|
| ![Ei](docs/img/00-ei.png)<br>Ei | ![Babytchi](docs/img/01-babytchi.png)<br>Babytchi | ![Marutchi](docs/img/02-marutchi.png)<br>Marutchi | ![Tamatchi](docs/img/03-tamatchi.png)<br>Tamatchi |
| ![Kuchitamatchi](docs/img/04-kuchitamatchi.png)<br>Kuchitamatchi | ![Mametchi](docs/img/05-mametchi.png)<br>Mametchi | ![Ginjirotchi](docs/img/06-ginjirotchi.png)<br>Ginjirotchi | ![Maskutchi](docs/img/07-maskutchi.png)<br>Maskutchi |
| ![Kuchipatchi](docs/img/08-kuchipatchi.png)<br>Kuchipatchi | ![Nyorotchi](docs/img/09-nyorotchi.png)<br>Nyorotchi | ![Tarakotchi](docs/img/10-tarakotchi.png)<br>Tarakotchi | ![Oyajitchi](docs/img/11-oyajitchi.png)<br>Oyajitchi |

## RAM-Adressen

Jede Adresse hält 4 Bit. Alles durch Beobachten und gezieltes Setzen im Emulator ermittelt.

| Adresse | Bedeutung |
|---|---|
| `0x10`/`0x11` | Uhr Sekunden (BCD, niedrig/hoch) |
| `0x12`/`0x13` | Uhr Minuten (BCD, niedrig/hoch) |
| `0x14`/`0x15` | Uhr Stunden (binär, `hoch*16+niedrig`); ein frisches Ei zeigt 32 = nicht gestellt |
| `0x2D` | 8, solange das Ruf-Icon leuchtet |
| `0x40` | Hunger 0–15, Herzen = `(Wert+1)//4`, Mahlzeit +4, fällt in Schritten von 4 |
| `0x41` | Glück 0–15, Herzen = `(Wert+1)//4`, Snack oder gewonnenes Spiel +4 |
| `0x42` | Pflegefehler 0–15 |
| `0x43` | Disziplin-Anzeige, +4 pro Schimpfen bei einem Schimpf-Ruf; bei jeder Verwandlung neu gesetzt |
| `0x46`/`0x47` | Gewicht (BCD) |
| `0x49` | wird 1, wenn das Tier krank war, bei der Verwandlung wieder 0 (nicht weiter geprüft) |
| `0x4B` | Licht: 15 an, 0 aus |
| `0x4D` | Anzahl Häufchen |
| `0x50` | Unterart: 1 Kind; Tamatchi 2 oder 3; Kuchitamatchi 4 oder 5; Erwachsene 15, nur der Maskutchi, der Oyajitchi wird, hat 6 |
| `0x51` | verpasste Schimpf-Rufe 0–15 |
| `0x54` | zählt bei jedem Aufwachen hoch (vermutlich das Alter, nicht geprüft) |
| `0x5D` | Charakter: 0 Ei oder tot, 1 Babytchi, 2 Marutchi, 3 Tamatchi, 4 Kuchitamatchi, 5 Mametchi, 6 Ginjirotchi, 7 Maskutchi, 8 Kuchipatchi, 9 Nyorotchi, 10 Tarakotchi, 11 Oyajitchi |
| `0x84` | im Spiel: ungleich 0, wenn die kommende Runde gewonnen wird (steht vor dem Tastendruck fest) |

## Weitere Beobachtungen

- Im Baby-Alter (65 Minuten) wird nichts gezählt.
- Schimpfen ohne Schimpf-Ruf bewirkt nichts.
- Im Spiel „links oder rechts“ steht das Ergebnis jeder Runde fest, bevor man drückt. Welche
  Taste man wann drückt, ist egal.
- Ein Ei schlüpft erst, nachdem die Uhr gestellt wurde.
- Lebensdauer bei guter Pflege, je ein Lauf im Zeitraffer, in Tagen seit dem Schlüpfen:
  Oyajitchi 24, Mametchi 20, Ginjirotchi 16, Maskutchi 16, Kuchipatchi 8, Tarakotchi 7,
  Nyorotchi 5.

## Aufbau

```
src/tamalib/     TamaLIB, unverändert bis auf eine Zeile in cpu.c (i = 0xFF in cpu_step)
src/tama_core.c  C-Hülle: ROM laden, Ticks laufen lassen, LCD/Ton/RAM auslesen, Zustand sichern
tama.py          ctypes-Anbindung
carebot.py       der Care-Bot
growth.py        Wachstumsregeln und Planung für ein Ziel
report.py        Tagesbericht per E-Mail
server.py        Emulator-Schleife und HTTP-Server
web/             Oberfläche, die Unterseite /bot und die Optionen /settings
lab/             die Experimente, aus denen die Tabellen stammen
```

## Lizenz

GPL-2.0, wie TamaLIB (siehe `LICENSE`). Tamagotchi ist eine Marke von Bandai; dieses Projekt hat
mit Bandai nichts zu tun.
