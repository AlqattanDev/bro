// BroBar — bro's face in the macOS menu bar.
//
// Polls ~/.bro/status-word and ~/.bro/mode twice a second and renders the word
// with a colored dot, using the exact palette of bin/bro-status-paint. Clicking
// the item runs bin/bro-wake. No dock icon (LSUIElement), no terminal or tmux
// required, and every file read is best-effort: a missing or unreadable file
// degrades to the same defaults bro-status-paint uses ("ready" / "call").

import AppKit
import Carbon.HIToolbox

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
    static var hotkeysTool: URL { home.appendingPathComponent("bin/bro-hotkeys") }
}

// MARK: - Hotkeys

/// One global summon key. Which key it is comes from bin/bro-hotkeys, which
/// reads ~/.bro/hotkeys — parsing stays in shell like every other bro control
/// file, so it is testable from bash and a typo there can never leave the app
/// unable to launch.
struct BroHotKey {
    /// Carbon hot key ids. Stable numbers, not indices: the handler switches
    /// on them.
    static let voiceID: UInt32 = 1
    static let textID: UInt32 = 2

    let id: UInt32
    let keyCode: UInt32
    let modifiers: UInt32
    let label: String

    /// What ships when ~/.bro/hotkeys is absent and when bin/bro-hotkeys
    /// cannot be run. Kept identical to the defaults documented in that script.
    /// ⌥§ and ⌃§: the § key left of 1, whose ⌘ variant belongs to Vox.
    static let fallback: [BroHotKey] = [
        BroHotKey(id: voiceID, keyCode: 10, modifiers: UInt32(optionKey), label: "⌥§"),
        BroHotKey(id: textID, keyCode: 10, modifiers: UInt32(controlKey), label: "⌃§"),
    ]

    /// Run bin/bro-hotkeys and read back its canonical lines:
    ///     voice keycode=10 modifiers=2048 label=⌥§
    ///     text off
    static func load() -> [BroHotKey] {
        let tool = BroPaths.hotkeysTool
        guard FileManager.default.isExecutableFile(atPath: tool.path) else { return fallback }
        let task = Process()
        task.executableURL = tool
        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = FileHandle.nullDevice
        var environment = ProcessInfo.processInfo.environment
        environment["BRO_HOME"] = BroPaths.home.path
        task.environment = environment
        guard (try? task.run()) != nil else { return fallback }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        task.waitUntilExit()
        guard task.terminationStatus == 0,
              let text = String(data: data, encoding: .utf8)
        else { return fallback }

        var keys: [BroHotKey] = []
        for line in text.components(separatedBy: .newlines) {
            let fields = line.split(separator: " ").map(String.init)
            guard let name = fields.first else { continue }
            let id: UInt32
            switch name {
            case "voice": id = voiceID
            case "text": id = textID
            default: continue
            }
            var values: [String: String] = [:]
            for field in fields.dropFirst() {
                let parts = field.split(separator: "=", maxSplits: 1).map(String.init)
                guard parts.count == 2 else { continue }
                values[parts[0]] = parts[1]
            }
            // `NAME off` is a deliberate disable, not a parse failure.
            guard let code = values["keycode"].flatMap(UInt32.init),
                  let modifiers = values["modifiers"].flatMap(UInt32.init)
            else { continue }
            keys.append(BroHotKey(
                id: id, keyCode: code, modifiers: modifiers, label: values["label"] ?? ""
            ))
        }
        // An entirely unreadable answer means something is wrong with the
        // script, not that Ali wanted no hotkeys at all.
        return keys.isEmpty ? fallback : keys
    }
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
    /// The typed-summon field (macos/BroSummon.swift). Separate window from the
    /// answer panel above, so the answer panel keeps its never-takes-focus
    /// guarantee while this one can be typed into.
    private let summon = BroSummon()
    private var hotKeyRefs: [EventHotKeyRef] = []
    /// Last rendered (word, mode). The status item is only touched when this
    /// changes, so the common case — nothing happening — costs two file reads.
    private var rendered: (word: String, mode: String)?

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.target = self
        statusItem.button?.action = #selector(clicked)

        panel.start()
        registerHotKeys()

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

    // MARK: - Global summon

    /// Carbon RegisterEventHotKey, deliberately, not an NSEvent global monitor:
    /// Carbon needs no permission grant at all, while a global monitor only
    /// delivers to a process trusted for Accessibility and would put a system
    /// prompt in front of Ali the first time he pressed the key. See
    /// ~/vox-mcp/macos/VoxStatus.swift:361 — Vox reached the same conclusion,
    /// and this is why bro can be summoned with zero terminals and zero grants.
    ///
    /// Only kEventHotKeyPressed is installed: bro's summons are taps. There is
    /// no hold gesture to tell apart, so there is nothing to do on release.
    private func registerHotKeys() {
        var eventType = EventTypeSpec(
            eventClass: OSType(kEventClassKeyboard),
            eventKind: OSType(kEventHotKeyPressed)
        )
        InstallEventHandler(
            GetApplicationEventTarget(),
            { _, event, userData in
                guard let userData, let event else { return noErr }
                var identifier = EventHotKeyID()
                let status = GetEventParameter(
                    event,
                    EventParamName(kEventParamDirectObject),
                    EventParamType(typeEventHotKeyID),
                    nil,
                    MemoryLayout<EventHotKeyID>.size,
                    nil,
                    &identifier
                )
                guard status == noErr else { return noErr }
                let delegate = Unmanaged<BroBar>.fromOpaque(userData).takeUnretainedValue()
                DispatchQueue.main.async { delegate.hotKeyFired(id: identifier.id) }
                return noErr
            },
            1,
            &eventType,
            Unmanaged.passUnretained(self).toOpaque(),
            nil
        )
        for key in BroHotKey.load() {
            var reference: EventHotKeyRef?
            let status = RegisterEventHotKey(
                key.keyCode,
                key.modifiers,
                EventHotKeyID(signature: OSType(0x4252_4F4F), id: key.id),  // 'BROO'
                GetApplicationEventTarget(),
                0,
                &reference
            )
            // Say which keys are live in logs/bro-bar.log. A hotkey another app
            // already owns fails here silently otherwise, and "nothing happens
            // when I press it" is the hardest kind of bug to see.
            if status == noErr, let reference {
                hotKeyRefs.append(reference)
                FileHandle.standardError.write(Data("bro-bar: hotkey \(key.label) registered\n".utf8))
            } else {
                FileHandle.standardError.write(Data(
                    "bro-bar: hotkey \(key.label) NOT registered (status \(status)) — another app may own it\n".utf8
                ))
            }
        }
    }

    /// Both summons return instantly. Voice hands off to bin/bro-talk (the same
    /// path F4 takes) and the transcript lands in the inbox queue; text opens
    /// the field, which enqueues on Enter. Neither one waits for an answer —
    /// the menu bar goes to `working` and the answer arrives in the panel.
    func hotKeyFired(id: UInt32) {
        switch id {
        case BroHotKey.voiceID:
            BroSummon.run(["voice"])
        case BroHotKey.textID:
            summon.toggle()
        default:
            return
        }
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
