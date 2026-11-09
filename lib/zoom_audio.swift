// Record one app's audio (default Zoom, us.zoom.xos) to raw PCM with ScreenCaptureKit; the fallback when OBS is not installed.
//   swift zoom_audio.swift <out.f32> [bundle id | all]     stops on SIGINT/SIGTERM. Needs Screen Recording permission.
import Foundation
import ScreenCaptureKit
import AVFoundation

let out = URL(fileURLWithPath: CommandLine.arguments[1])
let bundle = CommandLine.arguments.count > 2 ? CommandLine.arguments[2] : "us.zoom.xos"

// Raw mono float32 PCM at 48 kHz, appended as it arrives: the file grows every second and survives a crash.
// Convert: ffmpeg -f f32le -ar 48000 -ac 1 -i zoom.f32 zoom.m4a
final class Rec: NSObject, SCStreamOutput {
  let fh: FileHandle; var n = 0; var last = Date()
  init(_ url: URL) throws { FileManager.default.createFile(atPath: url.path, contents: nil); fh = try FileHandle(forWritingTo: url) }
  func stream(_ s: SCStream, didOutputSampleBuffer b: CMSampleBuffer, of t: SCStreamOutputType) {
    guard t == .audio, b.isValid else { return }
    try? b.withAudioBufferList { abl, _ in
      let bufs = Array(abl); guard let b0 = bufs.first, let p0 = b0.mData else { return }
      let frames = Int(b0.mDataByteSize) / 4; let ch0 = p0.assumingMemoryBound(to: Float.self)
      var mono = [Float](repeating: 0, count: frames)
      if bufs.count > 1, let p1 = bufs[1].mData { let ch1 = p1.assumingMemoryBound(to: Float.self)
        for i in 0..<frames { mono[i] = (ch0[i] + ch1[i]) / 2 } } else { for i in 0..<frames { mono[i] = ch0[i] } }
      mono.withUnsafeBytes { fh.write(Data($0)) }; n += frames
    }
    if Date().timeIntervalSince(last) > 60 { last = Date(); FileHandle.standardError.write("\(last) \(n / 48000) s\n".data(using: .utf8)!) }
  }
}

let rec = try Rec(out); var stream: SCStream?
Task {
  do {
    let c = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
    guard let d = c.displays.first else { exit(1) }
    let f: SCContentFilter
    if bundle == "all" { f = SCContentFilter(display: d, excludingApplications: [], exceptingWindows: []) }  // everything the Mac plays
    else { guard let app = c.applications.first(where: { $0.bundleIdentifier == bundle })
      else { FileHandle.standardError.write("app \(bundle) not found\n".data(using: .utf8)!); exit(1) }
      f = SCContentFilter(display: d, including: [app], exceptingWindows: []) }
    let cfg = SCStreamConfiguration(); cfg.capturesAudio = true; cfg.sampleRate = 48000; cfg.channelCount = 2
    cfg.width = 2; cfg.height = 2; cfg.minimumFrameInterval = CMTime(value: 1, timescale: 1)
    let s = SCStream(filter: f, configuration: cfg, delegate: nil)
    try s.addStreamOutput(rec, type: .audio, sampleHandlerQueue: DispatchQueue(label: "a"))
    try await s.startCapture(); stream = s
    FileHandle.standardError.write("capturing \(bundle) -> \(out.path)\n".data(using: .utf8)!)
  } catch { FileHandle.standardError.write("error: \(error)\n".data(using: .utf8)!); exit(1) }
}
func finish() {
  Task { try? await stream?.stopCapture(); try? rec.fh.close(); exit(0) }
}
signal(SIGINT, SIG_IGN); signal(SIGTERM, SIG_IGN)
let s1 = DispatchSource.makeSignalSource(signal: SIGINT); s1.setEventHandler(handler: finish); s1.resume()
let s2 = DispatchSource.makeSignalSource(signal: SIGTERM); s2.setEventHandler(handler: finish); s2.resume()
dispatchMain()
