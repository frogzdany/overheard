// MeetAudioHelper — Swift CLI that captures macOS system audio via
// ScreenCaptureKit and streams it as raw PCM to stdout.
//
// Subcommands:
//   list-devices              JSON of input devices on stdout
//   list-apps                 JSON of candidate apps (for per-app audio capture) on stdout
//   capture-system            int16 LE stereo @ 48kHz PCM on stdout, until SIGTERM/SIGINT
//   check-permission          exits 0 if Screen Recording permission is granted, 1 otherwise
//
// This binary is intended to be spawned by the Python engine as a subprocess.
//
// First-run permission: macOS will prompt the user to grant Screen Recording
// once a capture is started; subsequent runs of the *same signed binary*
// reuse the grant. For development, ad-hoc sign the build to keep the hash
// stable across rebuilds.

import Foundation

@main
struct MeetAudioHelper {
    static func main() async {
        let args = Array(CommandLine.arguments.dropFirst())

        guard let sub = args.first else {
            printUsage()
            exit(2)
        }

        switch sub {
        case "list-devices":
            DeviceLister.run()
        case "list-apps":
            AppLister.run()
        case "capture-system":
            await SystemCapture.run(args: Array(args.dropFirst()))
        case "check-permission":
            PermissionCheck.run()
        case "request-permission":
            PermissionCheck.runRequest()
        case "--help", "-h", "help":
            printUsage()
        default:
            FileHandle.standardError.write(Data("unknown subcommand: \(sub)\n".utf8))
            printUsage()
            exit(2)
        }
    }

    static func printUsage() {
        let usage = """
        MeetAudioHelper — system audio capture via ScreenCaptureKit.

        Subcommands:
          list-devices              Print input device list as JSON.
          list-apps                 Print candidate apps (regular, running, with a bundle id)
                                    as a JSON array on stdout. SCK-free (NSWorkspace only).
          capture-system            Stream system audio as int16 LE stereo PCM on stdout.
                                    Flags:
                                      --sample-rate <hz>          default 48000
                                      --status-fd <n>             write status lines as JSON to fd n
                                      --include-bundle-id <id>    repeatable; scope capture to these
                                                                   running apps instead of full system
          check-permission          Exit 0 if Screen Recording is granted, 1 otherwise.
          request-permission        Prompt for / register Screen Recording, then exit 0/1.
        """
        FileHandle.standardError.write(Data((usage + "\n").utf8))
    }
}
