# App-Hülle (Xcode, macOS)

Dieser Ordner ist noch leer bis auf die Konfigurationsvorlage. Das Xcode-Projekt wird auf dem Mac angelegt, weil SwiftUI weder auf Linux noch in CI ohne Apple-Toolchain baubar ist.

## Projekt anlegen

1. Xcode, neues Projekt, **App**, Interface SwiftUI, Sprache Swift.
2. Name `PPLCoach`, Ziel iOS 17 oder neuer, Orientierung nur Portrait.
3. Projekt in diesem Ordner (`App/`) ablegen.
4. `Core` als lokales Package einbinden: *File → Add Package Dependencies → Add Local* und den Ordner `../Core` wählen. Danach `PPLCoachCore` beim App-Target als Framework hinzufügen.

Die App-Hülle enthält nur Bildschirme und Systemanbindung. Ablauflogik, Metriken, Detektoren und Empfehlungsregeln bleiben im `Core`-Package, damit sie ohne Simulator testbar sind.

## Benötigte Capabilities und Berechtigungen

| Zweck | Eintrag |
| --- | --- |
| Fotos nach der Session | `NSCameraUsageDescription` |
| Sicherung von Datenbank und Fotos | iCloud (CloudKit oder iCloud Documents) |
| Whoop-Anmeldung | URL-Schema `pplcoach` für den OAuth-Rücksprung |
| Tokens | Keychain (keine Capability nötig, aber Access Group bewusst setzen) |

Kein Hintergrund-Modus für die Timer: Pause und Satzdauer werden aus Zeitstempeln der Wanduhr berechnet, nicht aus einem laufenden Timer-Objekt. Dadurch überleben sie Sperre, Anruf und Absturz. Der UI-Timer ist reine Anzeige.

Während einer offenen Session bleibt der Bildschirm an (`isIdleTimerDisabled`), und das Pausenende wird haptisch plus mit kurzem Ton gemeldet — im Stumm-Modus zählt die Haptik.

## Konfiguration

```bash
cp Config/Secrets.example.xcconfig Config/Secrets.xcconfig
```

Danach im Projekt als Configuration File hinterlegen. `Secrets.xcconfig` ist per `.gitignore` ausgeschlossen.
