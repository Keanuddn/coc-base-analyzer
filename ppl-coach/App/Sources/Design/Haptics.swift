import Foundation

#if canImport(UIKit)
import UIKit
import AudioToolbox
#endif

/// Rückmeldung, die man ohne Hinsehen bemerkt.
///
/// Das Pausenende **muss** spürbar sein: in der Pause liegt das Handy in der
/// Tasche oder auf der Bank, nicht in der Hand. Im Stumm-Modus zählt die
/// Haptik, deshalb immer beides.
enum Haptics {
    static var soundEnabled = true
    static var hapticsEnabled = true

    /// Kurzer Tap für Start, Stop und Stepper.
    static func tap() {
        #if canImport(UIKit)
        guard hapticsEnabled else { return }
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        #endif
    }

    /// Bestätigung nach dem Eintragen.
    static func success() {
        #if canImport(UIKit)
        guard hapticsEnabled else { return }
        UINotificationFeedbackGenerator().notificationOccurred(.success)
        #endif
    }

    /// Pausenende: deutlich, mehrfach, plus Ton.
    static func restFinished() {
        #if canImport(UIKit)
        if hapticsEnabled {
            let generator = UINotificationFeedbackGenerator()
            generator.notificationOccurred(.success)
            // Zweiter Impuls kurz danach, damit es auch in der Tasche auffällt.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
                UIImpactFeedbackGenerator(style: .heavy).impactOccurred()
            }
        }
        if soundEnabled {
            AudioServicesPlaySystemSound(1057)
        }
        #endif
    }
}
