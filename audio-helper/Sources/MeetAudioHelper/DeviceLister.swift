import AVFoundation
import Foundation

enum DeviceLister {
    struct DeviceInfo: Codable {
        let id: String
        let name: String
        let manufacturer: String
        let isDefault: Bool
    }

    struct Output: Codable {
        let devices: [DeviceInfo]
        let defaultId: String?
    }

    static func run() {
        // .external is macOS 14+; on 13 we fall back to the built-in type only.
        // External USB / Aggregate devices still show up via the default
        // discovery list on 13 via AVCaptureDevice.devices(for:) below.
        let deviceTypes: [AVCaptureDevice.DeviceType]
        if #available(macOS 14.0, *) {
            deviceTypes = [.builtInMicrophone, .external, .microphone]
        } else {
            deviceTypes = [.builtInMicrophone]
        }
        let session = AVCaptureDevice.DiscoverySession(
            deviceTypes: deviceTypes,
            mediaType: .audio,
            position: .unspecified
        )
        let defaultDevice = AVCaptureDevice.default(for: .audio)
        let infos = session.devices.map { d in
            DeviceInfo(
                id: d.uniqueID,
                name: d.localizedName,
                manufacturer: d.manufacturer,
                isDefault: d.uniqueID == defaultDevice?.uniqueID
            )
        }
        let payload = Output(devices: infos, defaultId: defaultDevice?.uniqueID)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        do {
            let data = try encoder.encode(payload)
            FileHandle.standardOutput.write(data)
            FileHandle.standardOutput.write(Data("\n".utf8))
        } catch {
            FileHandle.standardError.write(Data("encode failed: \(error)\n".utf8))
            exit(1)
        }
    }
}
