// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "MeetAudioHelper",
    platforms: [.macOS(.v13)],
    products: [
        .executable(name: "MeetAudioHelper", targets: ["MeetAudioHelper"]),
    ],
    targets: [
        .executableTarget(
            name: "MeetAudioHelper",
            path: "Sources/MeetAudioHelper"
        ),
    ]
)
