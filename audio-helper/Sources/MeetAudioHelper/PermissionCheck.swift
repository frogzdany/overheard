import CoreGraphics
import Foundation

enum PermissionCheck {
    /// Exit 0 if Screen Recording has been granted, 1 otherwise.
    ///
    /// We probe via `CGPreflightScreenCaptureAccess` which is the documented
    /// non-prompting test. Running it here — in the helper, the process that
    /// actually captures system audio — is what makes it authoritative; the
    /// engine sidecar is a different TCC identity and reports a false negative.
    static func run() {
        emit(granted: CGPreflightScreenCaptureAccess())
    }

    /// Trigger the Screen Recording prompt / register this helper in the
    /// Settings list, then report the resulting status. Exit 0 granted, 1 not.
    static func runRequest() {
        emit(granted: CGRequestScreenCaptureAccess())
    }

    private static func emit(granted: Bool) {
        let payload: [String: Any] = ["granted": granted, "platform": "macOS"]
        if let data = try? JSONSerialization.data(withJSONObject: payload),
           let s = String(data: data, encoding: .utf8) {
            FileHandle.standardOutput.write(Data((s + "\n").utf8))
        }
        exit(granted ? 0 : 1)
    }
}
