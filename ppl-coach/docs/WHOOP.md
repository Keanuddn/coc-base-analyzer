# Whoop-Integration

Stand der Recherche: August 2026. Whoop ist ab der ersten Version Teil der App.

## Zugang

- Aktive Whoop-Mitgliedschaft und eine registrierte App im Whoop-Developer-Dashboard
- OAuth 2.0 Authorization Code Flow
  - Autorisierung: `https://api.prod.whoop.com/oauth/oauth2/auth`
  - Token: `https://api.prod.whoop.com/oauth/oauth2/token`
- API-Basis: `https://api.prod.whoop.com/developer/v2`
- Eigener `User-Agent`-Header setzen
- Rate Limits: 100 Anfragen pro Minute, 10.000 pro Tag — für einen Nutzer unkritisch

### Scopes

| Scope | Wofür |
| --- | --- |
| `read:recovery` | Recovery-Score, HRV (RMSSD), Ruhepuls |
| `read:cycles` | physiologische Zyklen, Tages-Strain |
| `read:sleep` | Schlafdauer, Schlaf-Performance, Schlafphasen |
| `read:workout` | Whoop-Workout der Session (Strain, Herzfrequenz) |
| `read:profile` | Kontozuordnung |
| `read:body_measurement` | optional (Größe, Gewicht, max. Herzfrequenz) |

### Endpunkte

- `GET /cycle`, `GET /cycle/{id}`
- `GET /cycle/{id}/recovery`, `GET /cycle/{id}/sleep`
- `GET /recovery`
- `GET /activity/sleep`, `GET /activity/sleep/{id}`
- `GET /activity/workout`, `GET /activity/workout/{id}`

Alle Listen sind paginiert, maximal 25 Einträge, Cursor über `nextToken`.

## Fünf Eigenheiten, die das Design bestimmen

**1. Zyklen statt Kalendertage.** Whoop rechnet in physiologischen Zyklen mit Start, Ende und Zeitzonen-Offset. Eine Session wird deshalb nicht über das Datum zugeordnet, sondern über den Zyklus, in dessen Zeitraum der Trainingsbeginn fällt. Das löst Spätabend-Training und Reisen automatisch mit. Gespeichert werden `cycle_id` und `sleep_id`.

**2. Recovery ist ein Morgenwert.** Recovery entsteht erst, wenn der Schlafzyklus abgeschlossen ist. Vor dem Aufwachen gibt es keinen Wert für den Tag. Für ein Abendtraining liegt Recovery vor, bei sehr frühem Training eventuell nicht.

**3. Der Tageskontext wird nachträglich vollständig.** Der Tages-Strain ist erst nach Tagesende endgültig, das Whoop-Workout der Session ebenfalls. Der Tageskontext startet daher als `pending` und wird beim nächsten Sync `complete`. **Detektoren rechnen ausschließlich mit `complete`-Kontext**, sonst entstehen Befunde auf halben Daten.

**4. Kein Webhook ohne Server.** Whoop-Webhooks brauchen eine öffentlich erreichbare HTTPS-Adresse. Die App ist bewusst serverlos, also wird gepollt: beim App-Start, vor dem Session-Start und einmal morgens. Bei den Rate Limits völlig ausreichend.

**5. Rohwerte sind wenig wert, Abweichungen zählen.** HRV als Tageswert sagt kaum etwas — erst der Abstand zur eigenen Baseline über Wochen ist interpretierbar. Gleiches gilt abgeschwächt für Ruhepuls und Recovery. Deshalb beim ersten Verbinden mehrere Monate Historie nachladen, damit die Baseline sofort steht.

## Was Whoop nicht liefert

**Nähe zum Muskelversagen pro Satz.** Whoops *Muscular Load* enthält zwar eine Intensitätskomponente mit Ermüdungsprofil, aber präzise nur über *Strength Trainer* — also wenn Sätze, Wiederholungen und Gewichte in der Whoop-App geloggt werden. Das wäre doppelte Erfassung parallel zu dieser App, und das Ergebnis ist trotzdem eine aggregierte Zahl pro Workout statt pro Satz.

Ersatz: **Zeit pro Wiederholung** aus dem Satz-Timer. Bei gleicher Last werden die letzten Wiederholungen langsamer — derselbe Signaltyp, aber pro Satz und ohne Zusatzaufwand.

## Robustheit

- Eine Session startet **nie** verzögert wegen Whoop. Ohne Netz läuft alles normal, der Kontext wird später ergänzt.
- Tokens im Keychain, automatischer Refresh, klarer Weg zum erneuten Verbinden.
- Client-Secret nicht ins Repository — Whoops Bedingungen untersagen Zugangsdaten in offenen Projekten. Vorlage: `App/Config/Secrets.example.xcconfig`.
- Whoop-Daten bleiben auf dem Gerät.
- Bei getrennter oder ausgefallener Anbindung schweigen die betroffenen Detektoren; der Rest arbeitet weiter.

## Verhältnis zum Readiness-Tap

Der Tap am Session-Start (gut / okay / schlecht) bleibt trotz Whoop. Subjektives Gefühl und Recovery-Score widersprechen sich häufig, und dieser Widerspruch ist ein eigenes Signal: „fühlt sich mies an, Recovery grün“ ist etwas anderes als beides rot.
