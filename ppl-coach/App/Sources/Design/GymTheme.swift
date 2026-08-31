import SwiftUI

/// Gym-Konsole statt Fitness-Hochglanz.
///
/// Der Screen wird in 1,5 m Abstand, mit einer Hand und in kurzen Blicken
/// gelesen. Deshalb: drei klar unterscheidbare Modi, ein primärer Knopf, Zahlen
/// als eigentliche Oberfläche. Kein Neon, keine Verläufe, keine Streak-Karten.
enum GymTheme {
    /// Die drei Modi der Session. Farblich nicht zu verwechseln, damit du in
    /// zwei Sekunden weißt, ob du arbeitest, pausierst oder eintragen sollst.
    enum Mode {
        case work
        case rest
        case entry
        case warmup

        var accent: Color {
            switch self {
            case .work: return Color(red: 0.93, green: 0.55, blue: 0.20)
            case .rest: return Color(red: 0.29, green: 0.62, blue: 0.85)
            case .entry: return Color(red: 0.85, green: 0.85, blue: 0.87)
            case .warmup: return Color(red: 0.55, green: 0.55, blue: 0.58)
            }
        }

        var background: Color {
            switch self {
            case .work: return Color(red: 0.10, green: 0.07, blue: 0.04)
            case .rest: return Color(red: 0.04, green: 0.07, blue: 0.11)
            case .entry: return Color(red: 0.06, green: 0.06, blue: 0.07)
            case .warmup: return Color(red: 0.07, green: 0.07, blue: 0.08)
            }
        }

        var label: String {
            switch self {
            case .work: return "Satz läuft"
            case .rest: return "Pause"
            case .entry: return "Eintragen"
            case .warmup: return "Warm-up"
            }
        }
    }

    static let surface = Color(red: 0.10, green: 0.10, blue: 0.12)
    static let primaryText = Color(red: 0.96, green: 0.96, blue: 0.97)
    static let secondaryText = Color(red: 0.62, green: 0.62, blue: 0.66)
    static let stroke = Color(red: 0.20, green: 0.20, blue: 0.23)

    /// Timer und Kilogramm brauchen feste Ziffernbreite, sonst zappelt die
    /// Anzeige bei jedem Wechsel.
    static func timerFont(size: CGFloat) -> Font {
        .system(size: size, weight: .semibold, design: .rounded).monospacedDigit()
    }

    static func numberFont(size: CGFloat) -> Font {
        .system(size: size, weight: .bold, design: .rounded).monospacedDigit()
    }
}

/// Der eine große Knopf unten. Nie zwei gleich große Aktionen auf einem Screen.
struct PrimaryButton: View {
    let title: String
    let mode: GymTheme.Mode
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 26, weight: .bold, design: .rounded))
                .foregroundStyle(Color.black)
                .frame(maxWidth: .infinity)
                .frame(height: 92)
                .background(mode.accent, in: RoundedRectangle(cornerRadius: 20))
        }
        .buttonStyle(.plain)
        .contentShape(Rectangle())
    }
}

/// Zweitrangige Aktion -- optisch deutlich leiser als der primäre Knopf.
struct SecondaryButton: View {
    let title: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: 17, weight: .medium))
                .foregroundStyle(GymTheme.secondaryText)
                .frame(maxWidth: .infinity)
                .frame(height: 52)
                .overlay(
                    RoundedRectangle(cornerRadius: 14)
                        .stroke(GymTheme.stroke, lineWidth: 1)
                )
        }
        .buttonStyle(.plain)
    }
}

/// Große Stepper-Zeile für Zahlen. Im Gym tippt niemand in kleine Textfelder.
struct NumberStepper: View {
    let title: String
    let unit: String
    @Binding var value: Double
    let step: Double
    let format: (Double) -> String

    var body: some View {
        VStack(spacing: 10) {
            Text(title.uppercased())
                .font(.system(size: 13, weight: .semibold))
                .tracking(1.2)
                .foregroundStyle(GymTheme.secondaryText)

            HStack(spacing: 16) {
                stepButton("minus") {
                    value = max(0, value - step)
                }

                VStack(spacing: 0) {
                    Text(format(value))
                        .font(GymTheme.numberFont(size: 52))
                        .foregroundStyle(GymTheme.primaryText)
                    Text(unit)
                        .font(.system(size: 13, weight: .medium))
                        .foregroundStyle(GymTheme.secondaryText)
                }
                .frame(minWidth: 140)

                stepButton("plus") {
                    value += step
                }
            }
        }
    }

    private func stepButton(_ systemName: String, action: @escaping () -> Void) -> some View {
        Button(action: {
            action()
            Haptics.tap()
        }) {
            Image(systemName: systemName)
                .font(.system(size: 24, weight: .bold))
                .foregroundStyle(GymTheme.primaryText)
                .frame(width: 68, height: 68)
                .background(GymTheme.surface, in: RoundedRectangle(cornerRadius: 18))
        }
        .buttonStyle(.plain)
    }
}

extension Double {
    /// Deutsche Schreibweise mit Komma, ohne unnötige Nachkommastelle.
    var kgText: String {
        self == rounded()
            ? String(Int(self))
            : String(format: "%.1f", self).replacingOccurrences(of: ".", with: ",")
    }
}

extension TimeInterval {
    /// mm:ss für Timer.
    var clockText: String {
        let total = Int(rounded())
        return String(format: "%d:%02d", total / 60, total % 60)
    }
}
