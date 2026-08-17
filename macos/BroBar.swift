// BroBar — bro's face in the macOS menu bar.
//
// Polls ~/.bro/status-word and ~/.bro/mode twice a second and renders the word
// with a colored dot, using the exact palette of bin/bro-status-paint. Clicking
// the item runs bin/bro-wake. No dock icon (LSUIElement), no terminal or tmux
// required, and every file read is best-effort: a missing or unreadable file
// degrades to the same defaults bro-status-paint uses ("ready" / "call").

import AppKit

// MARK: - Paths

enum BroPaths {
    static let home: URL = {
        let env = ProcessInfo.processInfo.environment
        if let override = env["BRO_HOME"], !override.isEmpty {
            return URL(fileURLWithPath: (override as NSString).expandingTildeInPath)
        }
        return URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent(".bro")
    }()

    static var statusWord: URL { home.appendingPathComponent("status-word") }
    static var mode: URL { home.appendingPathComponent("mode") }
    static var wake: URL { home.appendingPathComponent("bin/bro-wake") }
}

/// Read a one-word control file, trimming all whitespace like
/// `tr -d '[:space:]'`. Any failure yields the caller's fallback.
func readWord(_ url: URL, fallback: String) -> String {
    guard let data = try? Data(contentsOf: url),
          let raw = String(data: data, encoding: .utf8)
    else { return fallback }
    let word = raw.components(separatedBy: .whitespacesAndNewlines).joined()
    return word.isEmpty ? fallback : word
}

// MARK: - Palette

/// Same mapping as bin/bro-status-paint. Keep the two in sync.
func color(for word: String) -> NSColor {
    switch word {
    case "starting", "working": return NSColor(hex: 0xe5c07b)
    case "speaking": return NSColor(hex: 0xc678dd)
    case "listening": return NSColor(hex: 0x61afef)
    case "ready": return NSColor(hex: 0x7dcea0)
    default: return NSColor(hex: 0xaaaaaa)
    }
}

/// Same mapping as bin/bro-status-paint: only quiet and ping are prefixed.
func prefix(for mode: String) -> String {
    switch mode {
    case "quiet": return "quiet "
    case "ping": return "ping "
    default: return ""
    }
}

extension NSColor {
    convenience init(hex: Int) {
        self.init(
            srgbRed: CGFloat((hex >> 16) & 0xff) / 255.0,
            green: CGFloat((hex >> 8) & 0xff) / 255.0,
            blue: CGFloat(hex & 0xff) / 255.0,
            alpha: 1.0
        )
    }
}

// MARK: - App

final class BroBar: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private var timer: Timer?
    /// The floating answer panel (macos/BroPanel.swift) lives in this same
    /// process: one binary, one pidfile, one thing for bin/bro to supervise.
    private let panel = BroPanel()
    /// Last rendered (word, mode). The status item is only touched when this
    /// changes, so the common case — nothing happening — costs two file reads.
    private var rendered: (word: String, mode: String)?

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.target = self
        statusItem.button?.action = #selector(clicked)

        panel.start()

        refresh()
        let timer = Timer(timeInterval: 0.5, repeats: true) { [weak self] _ in self?.refresh() }
        // .common keeps polling alive while a menu-tracking loop is running.
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    private func refresh() {
        let word = readWord(BroPaths.statusWord, fallback: "ready")
        let mode = readWord(BroPaths.mode, fallback: "call")
        if let rendered = rendered, rendered.word == word, rendered.mode == mode { return }
        rendered = (word, mode)

        guard let button = statusItem.button else { return }
        let title = NSMutableAttributedString(
            string: "● ",
            attributes: [
                .foregroundColor: color(for: word),
                .font: NSFont.systemFont(ofSize: 11),
            ]
        )
        title.append(NSAttributedString(
            string: prefix(for: mode) + word,
            attributes: [
                .foregroundColor: NSColor.labelColor,
                .font: NSFont.menuBarFont(ofSize: 0),
            ]
        ))
        button.attributedTitle = title
    }

    @objc private func clicked() {
        let wake = BroPaths.wake
        guard FileManager.default.isExecutableFile(atPath: wake.path) else { return }
        let task = Process()
        task.executableURL = wake
        task.arguments = ["menubar"]
        task.standardOutput = FileHandle.nullDevice
        task.standardError = FileHandle.nullDevice
        // Detached and unwaited: a wake that hangs or fails must never stall
        // the menu bar.
        try? task.run()
    }
}
// The entry point lives in macos/main.swift: once this app is more than one
// file, Swift only allows top-level statements there.
