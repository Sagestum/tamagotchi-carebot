# Experimente

Mit diesen Skripten wurden die RAM-Adressen und die Wachstumsregeln gefunden. Sie sind so
geblieben, wie sie beim Suchen entstanden sind.

```bash
make                 # baut libtamalab.so: der Emulator plus eine Funktion zum Schreiben ins RAM
python3 mkbase.py    # Spielstand eines Kindes kurz vor der Verwandlung (wird von exp3–exp7 gebraucht)
```

Die ROM muss unter `../tama/tama.b` liegen. Alles läuft im Zeitraffer ohne Server.

| Skript | Frage |
|---|---|
| `exp2.py A`…`G` | Sieben Leben mit unterschiedlicher Pflege; jede RAM-Änderung wird mitgeschrieben. `tl.py` zeigt daraus eine Zeitleiste für ausgewählte Adressen. |
| `exp8.py` | Ab welchem Wert ruft das Tier, und wann zählt die ROM einen Pflegefehler? |
| `exp9.py` | Worin unterscheidet sich das RAM bei Hunger-Ruf, Glück-Ruf und Schimpf-Ruf? |
| `exp10.py` | Was bewirkt Schimpfen ohne Schimpf-Ruf? |
| `exp3.py` | Kind → Teenager für alle Werte von Pflegefehlern, Disziplin-Anzeige und verpassten Rufen |
| `exp4.py`, `exp6.py` | Teenager → Erwachsener für alle 16 × 16 Zählerstände und alle vier Teenager-Arten |
| `exp7.py` | Welcher Maskutchi wird Oyajitchi, und wie alt werden die Erwachsenen? |
| `goaltest.py` | Der echte Care-Bot vom Ei an, einmal für jedes Ziel |

`lab.py` enthält das Gerüst: Emulator starten, RAM lesen und schreiben, einen Bot mit
Schaltern für absichtliche Vernachlässigung.

Die Uhr des Tiers wird beim Start auf die aktuelle Uhrzeit gestellt. Zeitangaben in den
Ausgaben hängen deshalb davon ab, wann ein Lauf gestartet wurde.
