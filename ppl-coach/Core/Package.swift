// swift-tools-version: 6.0
import PackageDescription

// iOS 17, damit Xcode das lokale Package dem App-Target zuordnen kann.
// Ohne UI-Abhängigkeiten: auf Linux bleibt `swift test` lauffähig.
let package = Package(
    name: "PPLCoachCore",
    platforms: [
        .iOS(.v17),
        .macOS(.v14)
    ],
    products: [
        .library(name: "PPLCoachCore", targets: ["PPLCoachCore"])
    ],
    targets: [
        .target(name: "PPLCoachCore"),
        .testTarget(name: "PPLCoachCoreTests", dependencies: ["PPLCoachCore"])
    ]
)
