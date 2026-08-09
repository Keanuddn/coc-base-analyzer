# CoC Base Analyzer

## Beschreibung

**CoC Base Analyzer** ist ein inoffizielles Fan-Projekt zur Analyse von Gegner-Basen in *Clash of Clans*. Anhand von Screenshots der gegnerischen Basis werden per Computer Vision Strukturen erkannt, der Basistyp klassifiziert, Fallen-Wahrscheinlichkeiten geschätzt und auf Basis von Rathaus-Level (TH) und Armee Angriffspläne vorgeschlagen.

Alle spielbezogenen Fakten stammen aus einer kuratierten Wissensbasis — nicht aus dem Speicher eines Sprachmodells.

## Architektur (Monorepo)

Das Projekt ist als Monorepo aufgebaut. Geplante bzw. vorgesehene Bereiche:

| Bereich | Zweck |
|--------|--------|
| `data-pipeline` | Ingestion, Labeling, Datensatz-Build |
| `ml` | Modelle, Training, Inferenz (CV/Klassifikation) |
| `knowledge-base` | Kuratierte Spielregeln, Truppen, Fallen, Meta |
| `backend` | API, Orchestrierung, Business-Logik |
| `frontend` | UI für Upload, Ergebnisse, Angriffspläne |
| `docs` | Spezifikation, ADRs, Betrieb |

Weitere Pakete können ergänzt werden, sobald die Implementierung startet.

## Setup

```bash
git clone <repository-url>
cd coc-base-analyzer
# Weitere Setup-Schritte folgen in späteren Phasen.
```

## Rechtliche Hinweise

Dieses Projekt ist **inoffizielles Fan-Content** und steht in **keiner Verbindung** zu Supercell. Es wird nicht von Supercell unterstützt oder empfohlen.

**Disclaimer (Supercell Fan Content Policy):**

This material is unofficial and is not endorsed by Supercell. For more information see Supercell's Fan Content Policy: www.supercell.com/fan-content-policy.

*Clash of Clans* ist eine Marke von Supercell. Alle Rechte liegen bei den jeweiligen Inhabern.
