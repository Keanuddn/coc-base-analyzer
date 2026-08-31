# App-Hülle (SwiftUI)

Xcode-Projekt: `PPLCoach.xcodeproj` in diesem Ordner (`ppl-coach/`).

## Ohne Git auf den Mac (empfohlen)

Xcode zeigt Git-Status, sobald `ppl-coach` **innerhalb** von `coc-base-analyzer` liegt.
Die App dann aus einem normalen Ordner starten — nicht aus dem Analyzer-Repo.

Im Terminal:

```bash
cd ~/coc-base-analyzer
git fetch origin
git checkout cursor/scaffold-ppl-coach-dcd1
git pull origin cursor/scaffold-ppl-coach-dcd1

rm -rf ~/PPLCoach
ditto ppl-coach ~/PPLCoach
rm -rf ~/Library/Developer/Xcode/DerivedData/PPLCoach-*

open ~/PPLCoach/PPLCoach.xcodeproj
```

Das alte Xcode-Fenster mit `coc-base-analyzer` schließen. In der neuen Instanz:
*Product → Clean Build Folder*, dann ⌘R.

`~/PPLCoach` hat **kein** Git. Signing-Team einmal setzen.

## Simulator starten (falls das Projekt schon liegt)

1. `PPLCoach.xcodeproj` öffnen — kein neues Projekt anlegen.
2. Schema **PPLCoach**, Destination ein iPhone-Simulator.
3. Signing: Team wählen. Für den Simulator reicht die persönliche Apple-ID.
4. ⌘R.

Beim ersten Öffnen löst Xcode das lokale Package `Core` (`PPLCoachCore`) auf.


## Was im Simulator anders ist

| Thema | Simulator | iPhone |
| --- | --- | --- |
| Kamera | Button heißt „Foto wählen“, nimmt die Mediathek | Livebild plus Schablone des Vorgängerfotos |
| Haptik / Ton | oft still | Pausenende spürbar plus Ton |
| iCloud | fällt auf lokalen App-Ordner zurück | gleiche Logik, Cloud wenn angemeldet |
| Whoop | braucht `Secrets.xcconfig`, sonst deaktiviert | gleich |

Debug-Builds haben unter *Mehr → Simulator* den Punkt **Beispieldaten laden**:
acht synthetische Wochen, damit Verlauf und Erkenntnisse nicht leer sind.

## Whoop (optional)

```bash
cp App/Config/Secrets.example.xcconfig App/Config/Secrets.xcconfig
```

Client-ID und Secret eintragen. `Secrets.xcconfig` ist gitignored. Ohne die
Datei startet die App trotzdem — Whoop bleibt getrennt.

URL-Schema `pplcoach` ist in der Info.plist eingetragen.

## Aufbau von `Sources/`

| Datei | Aufgabe |
| --- | --- |
| `PPLCoachApp.swift` | Einstieg, hält Store, Controller und Whoop-Sync |
| `Persistence/Store.swift` | Dateibasierter Speicher, Planfassungen, PPL-Warteschlange, Export |
| `Session/SessionController.swift` | Bindet die Zustandsmaschine aus `Core` an die Oberfläche |
| `Design/GymTheme.swift` | Drei Session-Modi, primärer Knopf, große Stepper |
| `Design/Haptics.swift` | Spürbares Pausenende, Ton plus Vibration |
| `Views/SessionView.swift` | Der geführte Ablauf: Vorschau, Satz, Eingabe, Pause |
| `Views/HomeView.swift` | Startbildschirm, Readiness-Tap, Abschluss |
| `Views/PhotoViews.swift` | Pose-Vorgabe, Kamera mit Schablone, Timeline |
| `Views/HistoryAndInsightsViews.swift` | Verlaufscharts und Befund-Karten |
| `Views/MyPlanAndSettingsViews.swift` | Mein Plan, Whoop, Körpergewicht, Export |
| `Whoop/WhoopAuth.swift` | OAuth, Keychain |
| `Whoop/WhoopSync.swift` | Polling-Client und Synchronisation |

Ablauflogik, Metriken, Detektoren, Empfehlungs- und Probenregeln liegen bewusst
**nicht** hier, sondern im `Core`-Package — dort sind sie ohne Simulator
getestet.

## Warum kein Hintergrund-Modus für die Timer

Pause und Satzdauer werden aus Zeitstempeln der Wanduhr berechnet, nicht von
einem laufenden Timer-Objekt heruntergezählt. Dadurch überleben sie
Bildschirmsperre, Anruf und Absturz: beim Fortsetzen wird die Restzeit neu
gerechnet. Der Timer in der Anzeige ist reine Darstellung.

Während einer offenen Session bleibt der Bildschirm an
(`isIdleTimerDisabled`), und das Pausenende wird haptisch plus mit kurzem Ton
gemeldet — im Stumm-Modus zählt die Haptik.
