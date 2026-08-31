# App-Hülle (SwiftUI, macOS/Xcode)

Der Swift-Code für die App liegt fertig in `Sources/`. Was fehlt, ist das
Xcode-Projekt selbst — das kann nur auf einem Mac erzeugt werden, weil SwiftUI
weder auf Linux noch ohne Apple-Toolchain baubar ist.

## Projekt anlegen

1. Xcode, neues Projekt, **App**, Interface SwiftUI, Sprache Swift.
2. Name `PPLCoach`, Ziel iOS 17 oder neuer, nur Portrait.
3. Projekt in diesem Ordner (`App/`) ablegen.
4. Den Ordner `Sources/` ins Projekt ziehen (*Create groups*, nicht kopieren).
5. `Core` als lokales Package einbinden: *File → Add Package Dependencies → Add Local*, Ordner `../Core` wählen, dann `PPLCoachCore` beim App-Target als Framework hinzufügen.
6. `PPLCoachApp.swift` enthält `@main` — die von Xcode erzeugte Vorlagendatei löschen.

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

## Benötigte Einträge in der Info.plist

| Zweck | Schlüssel |
| --- | --- |
| Fotos nach der Session | `NSCameraUsageDescription` |
| Whoop-Rücksprung | URL-Schema `pplcoach` unter `CFBundleURLTypes` |
| Whoop-Zugangsdaten | `WHOOP_CLIENT_ID`, `WHOOP_CLIENT_SECRET`, `WHOOP_REDIRECT_URI` (aus der xcconfig) |

Capability: **iCloud** (Documents oder CloudKit) für die Sicherung von Datenbank
und Fotos. Ein verlorenes iPhone darf nicht die ganze Historie kosten.

## Warum kein Hintergrund-Modus für die Timer

Pause und Satzdauer werden aus Zeitstempeln der Wanduhr berechnet, nicht von
einem laufenden Timer-Objekt heruntergezählt. Dadurch überleben sie
Bildschirmsperre, Anruf und Absturz: beim Fortsetzen wird die Restzeit neu
gerechnet. Der Timer in der Anzeige ist reine Darstellung.

Während einer offenen Session bleibt der Bildschirm an
(`isIdleTimerDisabled`), und das Pausenende wird haptisch plus mit kurzem Ton
gemeldet — im Stumm-Modus zählt die Haptik.

## Konfiguration

```bash
cp Config/Secrets.example.xcconfig Config/Secrets.xcconfig
```

Danach im Projekt als Configuration File hinterlegen und die Werte über
*Info.plist* an die App durchreichen. `Secrets.xcconfig` ist per `.gitignore`
ausgeschlossen — Whoops Nutzungsbedingungen untersagen Zugangsdaten in offenen
Projekten.

## Stand

Der Code ist vollständig geschrieben, aber **nicht kompiliert** — dafür fehlt
der Mac. Erwartbar sind beim ersten Build kleinere Anpassungen an Importen und
API-Signaturen. Die Logik dahinter ist über die 115 Tests im `Core`-Package
abgedeckt.
