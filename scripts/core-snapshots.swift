// Screenshots of the living core in each state, rendered by WebKit (the engine of the LAZIS
// window), from the dev-only preview page. No backend, no model, no microphone. (Phase 14.1)
//
//   cd apps/desktop && pnpm vite --port 5199 &        # serve ui/ (any free port)
//   swift scripts/core-snapshots.swift http://localhost:5199 OUT_DIR [suffix] [extra-query] [state]
//   swift scripts/core-snapshots.swift --clip=120 http://localhost:5199 OUT_DIR [suffix] …
//
// The window is placed off-screen and never activated, so nothing appears or takes focus.
import AppKit
import WebKit

// --clip=N: instead of one PNG per state, N JPEG frames (30 fps) into OUT_DIR/STATE[-suffix]/,
// for turning into a video (e.g. ffmpeg -framerate 30 -i %04d.jpg …).
let clip = CommandLine.arguments.first { $0.hasPrefix("--clip=") }.flatMap { Int($0.dropFirst(7)) }
let args = CommandLine.arguments.filter { !$0.hasPrefix("--clip=") }
guard args.count >= 3 else { print("usage: core-snapshots.swift BASE_URL OUT_DIR [suffix]"); exit(2) }
let base = args[1]
let out = URL(fileURLWithPath: args[2], isDirectory: true)
let suffix = args.count > 3 ? "-" + args[3] : ""
let extra = args.count > 4 ? "&" + args[4] : ""  // e.g. "bloom=0" (diagnosis)
let only = args.count > 5 ? args[5] : nil
try? FileManager.default.createDirectory(at: out, withIntermediateDirectories: true)

let shots: [(String, String)] = [
    ("idle", "0"), ("listening", "0.35"), ("thinking", "0"), ("speaking", "0.4"), ("error", "0"),
].filter { only == nil || $0.0 == only }

let app = NSApplication.shared
app.setActivationPolicy(.prohibited)
let size = NSRect(x: -20000, y: -20000, width: 900, height: 700)
let window = NSWindow(contentRect: size, styleMask: [.borderless], backing: .buffered, defer: false)
let view = WKWebView(frame: NSRect(origin: .zero, size: size.size), configuration: WKWebViewConfiguration())
window.contentView = view
window.orderBack(nil)

func capture(_ i: Int) {
    if i >= shots.count { exit(0) }
    let (state, level) = shots[i]
    let mode = clip.map { "dpr=1&seq=\($0)" } ?? "dpr=1.5&shot=1"
    let url = URL(string: "\(base)/dev/core-preview.html?state=\(state)&level=\(level)&\(mode)\(extra)")!
    view.load(URLRequest(url: url))
    var tries = 0
    if let n = clip {
        let dir = out.appendingPathComponent("\(state)\(suffix)", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        let here = "location.href === \(String(reflecting: url.absoluteString))"
        func fetch(_ k: Int) {
            if k >= n { print("wrote \(n) frames to \(dir.path)"); capture(i + 1); return }
            view.evaluateJavaScript("\(here) ? window.__frames[\(k)] : null") { value, _ in
                if let s = value as? String, let comma = s.firstIndex(of: ","), let data = Data(base64Encoded: String(s[s.index(after: comma)...])) {
                    try? data.write(to: dir.appendingPathComponent(String(format: "%04d.jpg", k)))
                    fetch(k + 1)
                } else { print("frame \(k) missing: \(state)"); exit(1) }
            }
        }
        func waitDone() {
            tries += 1
            view.evaluateJavaScript("\(here) && window.__done === true") { value, _ in
                if (value as? Bool) == true { fetch(0) }
                else if tries > 600 { print("timeout: \(state)"); exit(1) }
                else { DispatchQueue.main.asyncAfter(deadline: .now() + 0.2, execute: waitDone) }
            }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5, execute: waitDone)
        return
    }
    func poll() {
        tries += 1
        // Only the page just requested counts (the previous page may still be answering).
        let js = "location.href === \(String(reflecting: url.absoluteString)) ? (window.__shot ?? null) : null"
        view.evaluateJavaScript(js) { value, _ in
            if let s = value as? String, let comma = s.firstIndex(of: ",") , let data = Data(base64Encoded: String(s[s.index(after: comma)...])) {
                let file = out.appendingPathComponent("core-\(state)\(suffix).png")
                try? data.write(to: file)
                print("wrote \(file.path) (\(data.count) bytes)")
                capture(i + 1)
            } else if tries > 100 {
                print("timeout: \(state)"); exit(1)
            } else {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.2, execute: poll)
            }
        }
    }
    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5, execute: poll)
}
capture(0)
app.run()
