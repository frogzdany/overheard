// SystemCapture.swift
//
// Captures macOS system audio via ScreenCaptureKit (macOS 13+) and writes a
// raw PCM stream to stdout. Layout is hard-coded for the engine's expectations:
//   • int16 LE, signed
//   • 2 channels (system stereo), interleaved [L, R, L, R, ...]
//   • sample rate selectable via --sample-rate (default 48000)
//
// The downstream Python consumer reads frames from stdout as a continuous
// PCM stream — no framing protocol — until SIGTERM/SIGINT closes us.
//
// Status messages (start, errors, stop) are emitted as JSON lines to stderr
// or to the optional --status-fd file descriptor so the parent process can
// tell apart "audio is flowing" from "permission denied".

import AVFoundation
import CoreMedia
import Foundation
import ScreenCaptureKit

enum SystemCapture {
    static func run(args: [String]) async {
        var sampleRate: Int = 48_000
        var statusFD: Int32 = 2
        var includeBundleIDs: [String] = []

        var it = args.makeIterator()
        while let a = it.next() {
            switch a {
            case "--sample-rate":
                if let s = it.next(), let n = Int(s) { sampleRate = n }
            case "--status-fd":
                if let s = it.next(), let n = Int32(s) { statusFD = n }
            case "--include-bundle-id":
                if let s = it.next() { includeBundleIDs.append(s) }
            default:
                FileHandle.standardError.write(Data("unknown flag: \(a)\n".utf8))
            }
        }

        // Clamp the sample rate to a sane PCM range — anything outside it can't
        // be captured usefully and would mis-size buffers downstream.
        sampleRate = min(max(sampleRate, 8_000), 192_000)

        // Make sure --status-fd is an open, writable descriptor before we hand
        // it to StatusEmitter; otherwise fall back to stderr so status JSON
        // isn't silently lost (or written to a recycled fd).
        if statusFD != 2 && fcntl(statusFD, F_GETFL) == -1 {
            FileHandle.standardError.write(
                Data("invalid --status-fd \(statusFD); falling back to stderr\n".utf8))
            statusFD = 2
        }

        let status = StatusEmitter(fd: statusFD)

        guard #available(macOS 13.0, *) else {
            status.emit(level: "error",
                        message: "ScreenCaptureKit audio requires macOS 13 or later.")
            exit(78)
        }

        do {
            let runner = try await CaptureRunner(sampleRate: sampleRate,
                                                  includeBundleIDs: includeBundleIDs,
                                                  status: status)
            let code = await runner.run()
            if code != 0 { exit(code) }
        } catch {
            status.emit(level: "error", message: "fatal: \(error.localizedDescription)")
            exit(1)
        }
    }
}

// MARK: - Status emission

final class StatusEmitter: @unchecked Sendable {
    let fd: Int32
    private let handle: FileHandle
    init(fd: Int32) {
        self.fd = fd
        self.handle = FileHandle(fileDescriptor: fd, closeOnDealloc: false)
    }
    func emit(level: String, message: String, extra: [String: String] = [:]) {
        var payload: [String: Any] = [
            "level": level,
            "ts": Date().timeIntervalSince1970,
            "message": message,
        ]
        for (k, v) in extra { payload[k] = v }
        if let data = try? JSONSerialization.data(withJSONObject: payload),
           let s = String(data: data, encoding: .utf8) {
            handle.write(Data((s + "\n").utf8))
        }
    }
}

// MARK: - Capture runner

@available(macOS 13.0, *)
final class CaptureRunner: NSObject, SCStreamDelegate, SCStreamOutput, @unchecked Sendable {
    let sampleRate: Int
    let status: StatusEmitter
    // Implicitly-unwrapped so the stream can be created *after* super.init():
    // SCStream only takes its delegate at init time, and `self` isn't usable
    // until NSObject is initialized.
    private(set) var stream: SCStream!
    let outputQueue = DispatchQueue(label: "meet.audio.output", qos: .userInteractive)
    let stdoutHandle = FileHandle.standardOutput
    let stopSemaphore = DispatchSemaphore(value: 0)
    var signalSources: [DispatchSourceSignal] = []
    // Set by didStopWithError; read by run() after the semaphore, whose
    // signal/wait pair provides the memory barrier.
    private var streamDied = false

    init(sampleRate: Int, includeBundleIDs: [String], status: StatusEmitter) async throws {
        self.sampleRate = sampleRate
        self.status = status
        super.init()

        let content = try await SCShareableContent.excludingDesktopWindows(
            false, onScreenWindowsOnly: false
        )
        guard let display = content.displays.first else {
            throw NSError(domain: "MeetAudioHelper", code: 1,
                          userInfo: [NSLocalizedDescriptionKey:
                                     "no displays found — cannot create capture filter"])
        }

        let filter: SCContentFilter
        if includeBundleIDs.isEmpty {
            filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
        } else {
            let wanted = Set(includeBundleIDs.map { $0.lowercased() })
            let matchedApps = content.applications.filter {
                wanted.contains($0.bundleIdentifier.lowercased())
            }
            guard !matchedApps.isEmpty else {
                throw NSError(domain: "MeetAudioHelper", code: 2,
                              userInfo: [NSLocalizedDescriptionKey:
                                         "no running application matched --include-bundle-id \(includeBundleIDs.joined(separator: ", "))"])
            }
            filter = SCContentFilter(display: display, including: matchedApps, exceptingWindows: [])
            status.emit(level: "info", message: "app-scoped capture",
                        extra: ["bundleIDs": matchedApps.map { $0.bundleIdentifier }.joined(separator: ","),
                                "matchedCount": String(matchedApps.count)])
        }

        let config = SCStreamConfiguration()
        config.capturesAudio = true
        config.excludesCurrentProcessAudio = true
        config.sampleRate = sampleRate
        config.channelCount = 2
        // We don't actually want video, but SCK still needs a video config.
        // Use tiny frames + the lowest framerate to minimize work.
        config.width = 2
        config.height = 2
        config.minimumFrameInterval = CMTime(value: 1, timescale: 1)
        config.queueDepth = 3

        // delegate: self is what delivers didStopWithError. Without it, a
        // stream teardown (display change, another capture, replayd restart)
        // is silent: this process keeps running and the engine keeps reading
        // an open-but-dry pipe.
        self.stream = SCStream(filter: filter, configuration: config, delegate: self)

        try stream.addStreamOutput(self, type: .audio,
                                   sampleHandlerQueue: outputQueue)
        // SCK *requires* a screen output to be registered even if we don't want video.
        try stream.addStreamOutput(self, type: .screen,
                                   sampleHandlerQueue: outputQueue)
    }

    func run() async -> Int32 {
        installSignalHandlers()
        do {
            try await stream.startCapture()
            status.emit(level: "info",
                        message: "capture started",
                        extra: ["sampleRate": String(sampleRate), "channels": "2"])
        } catch {
            status.emit(level: "error",
                        message: "startCapture failed: \(error.localizedDescription)")
            exit(74)
        }
        // Park until signaled.
        await withCheckedContinuation { (cont: CheckedContinuation<Void, Never>) in
            DispatchQueue.global(qos: .background).async {
                self.stopSemaphore.wait()
                cont.resume()
            }
        }
        if streamDied {
            // The stream is already gone; stopCapture would only produce
            // "already stopped". Exit non-zero so the parent knows this was
            // not a clean shutdown and restarts the capture.
            status.emit(level: "info", message: "exiting after stream death")
            return 69   // EX_UNAVAILABLE
        }
        do {
            try await stream.stopCapture()
        } catch {
            status.emit(level: "warn", message: "stopCapture: \(error.localizedDescription)")
        }
        status.emit(level: "info", message: "capture stopped")
        return 0
    }

    // MARK: SCStreamDelegate

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        streamDied = true
        status.emit(level: "error",
                    message: "stream stopped: \(error.localizedDescription)",
                    extra: ["code": "stream-died"])
        stopSemaphore.signal()
    }

    // MARK: SCStreamOutput

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
                of outputType: SCStreamOutputType) {
        guard outputType == .audio, sampleBuffer.isValid,
              let formatDesc = sampleBuffer.formatDescription else { return }

        // Extract the AudioBufferList from the sample buffer. We don't know
        // up-front how many buffers (planar streams give us one buffer per
        // channel), so we ask CoreMedia for the required size first, then
        // allocate exactly that and call again.
        let frameCount = Int(CMSampleBufferGetNumSamples(sampleBuffer))
        if frameCount == 0 { return }

        var sizeNeeded: Int = 0
        let probe = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sampleBuffer,
            bufferListSizeNeededOut: &sizeNeeded,
            bufferListOut: nil,
            bufferListSize: 0,
            blockBufferAllocator: kCFAllocatorDefault,
            blockBufferMemoryAllocator: kCFAllocatorDefault,
            flags: 0,
            blockBufferOut: nil
        )
        guard probe == noErr, sizeNeeded > 0 else {
            status.emit(level: "warn", message: "CMSampleBuffer ABL probe failed: \(probe)")
            return
        }

        let abListRaw = UnsafeMutableRawPointer.allocate(
            byteCount: sizeNeeded,
            alignment: MemoryLayout<AudioBufferList>.alignment
        )
        defer { abListRaw.deallocate() }
        let abListPtr = abListRaw.bindMemory(to: AudioBufferList.self, capacity: 1)

        var blockBufferOut: CMBlockBuffer?
        let st = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sampleBuffer,
            bufferListSizeNeededOut: nil,
            bufferListOut: abListPtr,
            bufferListSize: sizeNeeded,
            blockBufferAllocator: kCFAllocatorDefault,
            blockBufferMemoryAllocator: kCFAllocatorDefault,
            flags: kCMSampleBufferFlag_AudioBufferList_Assure16ByteAlignment,
            blockBufferOut: &blockBufferOut
        )
        guard st == noErr else {
            status.emit(level: "warn", message: "CMSampleBuffer ABL fetch failed: \(st)")
            return
        }

        // SCK delivers float32, non-interleaved (planar) per Apple's docs.
        let asbd = formatDesc.audioStreamBasicDescription
        guard let format = asbd else { return }
        let channelCount = Int(format.mChannelsPerFrame)
        let bufferList = UnsafeMutableAudioBufferListPointer(abListPtr)

        // We always want 2 channels out (interleaved int16 LE). If we got mono,
        // duplicate to L/R. If we got >2, mix all into L+R via simple average.
        var leftFloat = [Float](repeating: 0, count: frameCount)
        var rightFloat = [Float](repeating: 0, count: frameCount)

        if bufferList.count == 1 {
            // interleaved data on a single buffer
            let mBuf = bufferList[0]
            let data = mBuf.mData?.assumingMemoryBound(to: Float.self)
            if let data = data {
                for i in 0..<frameCount {
                    if channelCount == 1 {
                        let v = data[i]
                        leftFloat[i] = v
                        rightFloat[i] = v
                    } else {
                        leftFloat[i] = data[i * channelCount]
                        rightFloat[i] = data[i * channelCount + 1]
                    }
                }
            }
        } else {
            // planar — each buffer is one channel
            let ch0 = bufferList[0].mData?.assumingMemoryBound(to: Float.self)
            let ch1 = bufferList.count > 1
                ? bufferList[1].mData?.assumingMemoryBound(to: Float.self)
                : ch0
            if let ch0 = ch0 {
                for i in 0..<frameCount { leftFloat[i] = ch0[i] }
            }
            if let ch1 = ch1 {
                for i in 0..<frameCount { rightFloat[i] = ch1[i] }
            } else {
                rightFloat = leftFloat
            }
        }

        // Float32 [-1, 1] → int16 with clipping, interleaved.
        var interleaved = [Int16](repeating: 0, count: frameCount * 2)
        for i in 0..<frameCount {
            let l = max(-1.0, min(1.0, leftFloat[i])) * 32767.0
            let r = max(-1.0, min(1.0, rightFloat[i])) * 32767.0
            interleaved[i * 2] = Int16(l)
            interleaved[i * 2 + 1] = Int16(r)
        }

        interleaved.withUnsafeBufferPointer { ptr in
            let data = Data(buffer: ptr)
            stdoutHandle.write(data)
        }
    }

    // MARK: Signal handling

    func installSignalHandlers() {
        // DispatchSourceSignal lets us handle SIGINT/SIGTERM on a normal
        // queue, side-stepping the very limited set of operations allowed
        // inside a C signal handler.
        signal(SIGINT, SIG_IGN)
        signal(SIGTERM, SIG_IGN)
        signal(SIGPIPE, SIG_IGN)
        let sigQueue = DispatchQueue(label: "meet.audio.signals")
        for sig in [SIGINT, SIGTERM] {
            let src = DispatchSource.makeSignalSource(signal: sig, queue: sigQueue)
            src.setEventHandler { [weak self] in
                self?.stopSemaphore.signal()
            }
            src.resume()
            // Keep a strong ref via a closure capture — DispatchSourceSignal
            // is auto-cancelled when the source goes out of scope.
            signalSources.append(src)
        }
    }
}
