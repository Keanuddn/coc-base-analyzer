# PPL Coach

Persönliche iOS-App, die Satz für Satz durch einen festen Push/Pull/Legs-Split führt, jede relevante Zahl erfasst und später begründete Zusammenhänge zwischen Trainingsdaten, Whoop-Kontext und sichtbarem Fortschritt erkennt.

Ein Nutzer, ein Plan, ein iPhone. Kein Server, keine Plan-Erstellung für andere.

Der vollständige Produktplan liegt in [docs/PLAN.md](docs/PLAN.md).

## Die drei Regeln, die alles andere bestimmen

**Timer-Rhythmus.** Der Satz-Timer wird immer manuell gestartet und gestoppt — nur so ist die Dauer echte Arbeitszeit und nicht der Weg zur Maschine. Beim Stoppen startet der Pausen-Timer und läuft im Hintergrund weiter, auch während die Eingabe von Wiederholungen und Gewicht sichtbar ist. Nach der Eingabe erscheint derselbe Timer mit der Restzeit. Erst wenn die Pause vorbei ist, wird der nächste Satz freigegeben.

**Last-Empfehlung.** Immer sichtbar, sobald eine Übung startet, nie leer. Gesteigert wird nur, wenn *jeder* Arbeitssatz die obere Wiederholungsgrenze erreicht hat. Gesenkt nur, wenn mindestens ein Satz unter die untere Grenze fällt. Alles andere heißt halten. Es gibt keinen Übernehmen-Button: das eingetragene Gewicht ist die Entscheidung.

**Analyse lügt nicht.** Metriken, Detektoren und die Bewertung von Proben sind deterministisch und getestet. Ein Sprachmodell darf Lösungen vorschlagen und formulieren, sieht aber nie Rohdaten und rechnet nie. Fehlende Daten führen zu Schweigen, nicht zu Vermutungen.

## Aufbau

| Ort | Inhalt | Wo baubar |
| --- | --- | --- |
| `Core/` | Swift Package ohne UI: Ablauf-Zustandsmaschine, Metriken, Detektoren, Empfehlungsregeln, synthetischer Datengenerator | plattformunabhängig, auch Linux/CI |
| `App/` | SwiftUI-App, Whoop-OAuth, Kamera, Keychain, iCloud | nur macOS mit Xcode |
| `docs/` | Produktplan und Whoop-API-Notizen | — |

Die Trennung ist Absicht: die Logik, in der Fehler wehtun, ist ohne Simulator testbar.

## Core bauen und testen

```bash
cd Core
swift build
swift test
```

Aktuell 115 Tests. Jeder Detektor hat zwei: einen, der einen eingebauten Effekt
in synthetischen Daten finden muss, und einen Null-Test mit vertauschten Pausen,
in dem er **schweigen** muss. Ein Detektor, der auf Rauschen anspringt, ist
kaputt — der Null-Test hat genau das einmal aufgedeckt.

## App bauen

Xcode-Projekt auf dem Mac anlegen, `Core` als lokales Package einbinden. Details und benötigte Capabilities in [App/README.md](App/README.md).

## Whoop

Ab der ersten Version dabei. Einrichtung, Scopes und die Eigenheiten der API (physiologische Zyklen statt Kalendertage, Recovery erst nach dem Aufwachen, nachträglich vollständiger Tageskontext) stehen in [docs/WHOOP.md](docs/WHOOP.md).

Zugangsdaten gehören **nicht** ins Repository. Vorlage: `App/Config/Secrets.example.xcconfig`.

## Was drin ist

**Core (gebaut und getestet)**

- Der PPL-Plan als versionierte Daten, inklusive der Positionsregel für Cable Flies und der Warm-ups direkt vor ihrer Arbeitsübung
- Zustandsmaschine für den geführten Ablauf: Satz-Timer manuell, Pause läuft während der Eingabe weiter, Warm-ups ohne Pausenzwang, Supersets mit Pause erst nach der zweiten Übung
- Fortsetzen nach Sperre und Absturz, Restpause aus Zeitstempeln
- Last-Empfehlung nach dem schwächsten Arbeitssatz, Gewichtsschritte pro Übung
- Störungs-Marker mit drei Kategorien; von außen verursachte Pausen gelten als saubere Dosis, eigene nicht
- Metriken, elf Detektoren mit Gates und Schweigeregeln, Ranking und Karten aus Textbausteinen
- Proben: Laufzeit und Erfolgsschwelle aus der eigenen Streuung, keine überlappenden Messungen
- Whoop v2: Zyklus-Zuordnung, Baselines, Kontext erst vollständig wenn ausgewertet
- Export als JSON und CSV

**App (geschrieben, noch nicht kompiliert)**

Alle Bildschirme, Persistenz, Whoop-OAuth und Haptik liegen in `App/Sources/`.
Das Xcode-Projekt entsteht auf dem Mac, siehe [App/README.md](App/README.md).

## Was noch fehlt

- Xcode-Projekt anlegen und den ersten Build durchziehen
- Whoop-App im Developer-Dashboard registrieren, Zugangsdaten in die xcconfig
- iCloud-Sicherung einrichten
- Danach: mehrere Wochen im Gym benutzen, bevor an der Analyse weitergebaut wird — sie braucht ohnehin erst Daten
