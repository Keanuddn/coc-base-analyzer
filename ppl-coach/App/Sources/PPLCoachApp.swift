import SwiftUI
import PPLCoachCore

@main
struct PPLCoachApp: App {
    @StateObject private var store: Store
    @StateObject private var controller: SessionController
    @StateObject private var whoop = WhoopSync()

    init() {
        let store = Store()
        _store = StateObject(wrappedValue: store)
        _controller = StateObject(wrappedValue: SessionController(store: store))
    }

    var body: some Scene {
        WindowGroup {
            RootView(controller: controller)
                .environmentObject(store)
                .environmentObject(whoop)
                .task {
                    // Whoop-Kontext wird nachträglich vollständig: Recovery
                    // kommt morgens, der Tages-Strain erst nach Tagesende.
                    await whoop.sync(into: store)
                }
        }
    }
}

/// Entweder Startbildschirm oder die Session -- die Session übernimmt das Gerät
/// vollständig, bis sie fertig oder abgebrochen ist.
struct RootView: View {
    @EnvironmentObject private var store: Store
    @EnvironmentObject private var whoop: WhoopSync
    @ObservedObject var controller: SessionController

    var body: some View {
        Group {
            if controller.isRunning {
                SessionView(controller: controller)
            } else {
                HomeView(controller: controller)
            }
        }
        .preferredColorScheme(.dark)
        .onChange(of: controller.isRunning) { _, isRunning in
            // Vor dem Session-Start noch einmal Whoop holen, damit der
            // Recovery-Wert des Tages vorliegt.
            if isRunning {
                Task { await whoop.sync(into: store) }
            }
        }
    }
}
