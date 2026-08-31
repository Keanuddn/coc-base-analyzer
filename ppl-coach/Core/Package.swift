// swift-tools-version: 6.0
import PackageDescription

// Bewusst ohne Plattform-Einschränkung und ohne UI-Abhängigkeiten:
// dieses Package muss auch ohne Xcode und Simulator baubar und testbar sein.
let package = Package(
    name: "PPLCoachCore",
    products: [
        .library(name: "PPLCoachCore", targets: ["PPLCoachCore"])
    ],
    targets: [
        .target(name: "PPLCoachCore"),
        .testTarget(name: "PPLCoachCoreTests", dependencies: ["PPLCoachCore"])
    ]
)
