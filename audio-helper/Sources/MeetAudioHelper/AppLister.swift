import AppKit
import Foundation

enum AppLister {
    struct AppInfo: Codable {
        let bundleId: String
        let name: String
        let pid: Int
    }

    static func run() {
        let apps = NSWorkspace.shared.runningApplications
            .filter { $0.activationPolicy == .regular && $0.bundleIdentifier != nil }
            .map { app -> AppInfo in
                AppInfo(
                    bundleId: app.bundleIdentifier!,
                    name: app.localizedName ?? app.bundleIdentifier!,
                    pid: Int(app.processIdentifier)
                )
            }
            .sorted { $0.name.localizedCaseInsensitiveCompare($1.name) == .orderedAscending }

        let encoder = JSONEncoder()
        do {
            let data = try encoder.encode(apps)
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data("\n".utf8))
        } catch {
            FileHandle.standardError.write(Data("encode failed: \(error)\n".utf8))
            exit(1)
        }
    }
}
