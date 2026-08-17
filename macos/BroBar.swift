// BroBar — bro's face in the macOS menu bar.
//
// Polls ~/.bro/state/status-word and ~/.bro/state/mode twice a second and renders the word
// with a colored dot, using the exact palette of bin/bro-status-paint. Clicking
// the item opens the answer panel. No dock icon (LSUIElement), no terminal or tmux
// required, and every file read is best-effort: a missing or unreadable file
// degrades to the same defaults bro-status-paint uses ("ready" / "call").
//
// It is also the ONLY voice status item on screen. While BroBar runs it claims
// the menu bar through bin/bro-status-host (see that script for the protocol)
// and Vox hides its own item, so "speaking" and "listening" are said once
// instead of twice. Everything Vox's item did is therefore done here: the red
// live-mic glyph, its tooltips, a left-click that ends the turn while the mic is
// hot, and a right-click menu carrying its controls. Vox stays reachable and
// unaware of bro — the claim can be dropped from this very menu, and Vox's item
// comes straight back.

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

    static var state: URL { home.appendingPathComponent("state") }
    /// Live location is state/; the root path is the pre-state/ layout, kept
    /// as a read fallback so a bar launched mid-upgrade never goes blind.
    static var statusWord: URL { state.appendingPathComponent("status-word") }
    static var statusWordLegacy: URL { home.appendingPathComponent("status-word") }
    static var mode: URL { state.appendingPathComponent("mode") }
    static var modeLegacy: URL { home.appendingPathComponent("mode") }
    /// Which agent is behind all of this (grok/claude/codex) — tooltip only.
    static var backend: URL { state.appendingPathComponent("backend") }
    /// The next thing bro will speak up about, maintained by bin/bro-remind.
    /// One small file, so the twice-a-second poll never scans a directory.
    static var nextReminder: URL { state.appendingPathComponent("next-reminder") }
    /// Asks waiting for the backend. Counted here by directory listing, which
    /// is exactly what bin/bro-queue-count does — that script is the canonical,
    /// tested spelling of the same rule.
    static var inboxPending: URL { home.appendingPathComponent("inbox/pending") }
    /// Where a "down" tooltip finds its cause (last line is the why).
    static var backendLog: URL { home.appendingPathComponent("logs/backend.log") }
    static var wake: URL { home.appendingPathComponent("bin/bro-wake") }
    static var hotkeysTool: URL { home.appendingPathComponent("bin/bro-hotkeys") }
    static var statusHostTool: URL { home.appendingPathComponent("bin/bro-status-host") }

    /// Vox's own directory. Only ever read for the control token and opened in
    /// Finder from the menu — bro never writes Vox's state.
    static var voxHome: URL {
        let env = ProcessInfo.processInfo.environment
        if let override = env["VOX_HOME"], !override.isEmpty {
            return URL(fileURLWithPath: (override as NSString).expandingTildeInPath)
        }
        return URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent(".vox")
    }
}

// MARK: - Vox

/// Everything the menu bar needs to know about the voice service, in the shape
/// Vox's own status item used. It is `Equatable` so a render can be skipped when
/// nothing moved, exactly like the word/mode pair.
struct VoxSnapshot: Equatable {
    var reachable = false
    var state = ""
    var micOpen = false
    /// Vox is speaking *and* listening: talk over it to interrupt. Bro's status
    /// word says only "speaking", so without this the live mic would vanish.
    var bargeIn = false
    var detail = ""
    var lastStopReason = ""
    var ioMode = "talk"
    var lastSpokenAgent = ""
    var agents: [String] = []
    var notesWaiting: [String] = []
}

/// bro's side of the Vox HTTP contract: the same `/health` poll and `/control`
/// POST that Vox's own status item makes, so the controls that used to live
/// behind that icon still work now that it is hidden. Vox knows nothing about
/// this — the endpoint is the one every Vox client already uses.
final class VoxLink {
    private(set) var snapshot = VoxSnapshot()
    private var inFlight = false
    private let baseURL: URL = {
        let env = ProcessInfo.processInfo.environment
        if let override = env["VOX_URL"], let url = URL(string: override) { return url }
        return URL(string: "http://127.0.0.1:8766")!
    }()

    /// True once Vox has answered at least once. An "offline" warning is only
    /// honest about a service that was there; on a machine with no Vox at all
    /// the menu bar must stay quiet.
    private(set) var everReachable = false

    func poll(_ completion: @escaping () -> Void) {
        guard !inFlight else { return }
        inFlight = true
        var request = URLRequest(url: baseURL.appendingPathComponent("health"))
        request.timeoutInterval = 1.0
        URLSession.shared.dataTask(with: request) { [weak self] data, _, _ in
            DispatchQueue.main.async {
                guard let self else { return }
                self.inFlight = false
                guard
                    let data,
                    let payload = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                else {
                    // Unreachable is a state, not an error: keep the last known
                    // words, drop everything that claims the mic is live.
                    var offline = VoxSnapshot()
                    offline.detail = self.snapshot.detail
                    self.snapshot = offline
                    completion()
                    return
                }
                self.everReachable = true
                var next = VoxSnapshot()
                next.reachable = true
                next.state = ((payload["state"] as? String)
                    ?? (payload["status"] as? String) ?? "online").lowercased()
                next.micOpen = (payload["microphone_open"] as? Bool) ?? false
                next.bargeIn = (payload["mic_armed_for_barge_in"] as? Bool) ?? false
                next.detail = (payload["detail"] as? String) ?? ""
                next.lastStopReason = (payload["last_stop_reason"] as? String) ?? ""
                next.ioMode = ((payload["io_mode"] as? String) ?? "talk").lowercased()
                next.lastSpokenAgent = (payload["last_spoken_agent"] as? String) ?? ""
                next.agents = (payload["agents"] as? [String]) ?? []
                next.notesWaiting = (payload["notes_waiting"] as? [String]) ?? []
                self.snapshot = next
                completion()
            }
        }.resume()
    }

    /// Fire and forget, like every control Vox's own menu sent. Never serialized:
    /// a swallowed `end_turn` would leave the microphone open with no way to
    /// close it, which is the failure Vox's own comment warns about.
    func send(_ action: String, extra: [String: Any] = [:]) {
        var request = URLRequest(url: baseURL.appendingPathComponent("control"))
        request.httpMethod = "POST"
        request.timeoutInterval = 6.0
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue("bro-bar", forHTTPHeaderField: "X-Vox-Control-Source")
        if let token = try? String(
            contentsOf: BroPaths.voxHome.appendingPathComponent("control.token"), encoding: .utf8
        ) {
            request.setValue(
                token.trimmingCharacters(in: .whitespacesAndNewlines), forHTTPHeaderField: "X-Vox-Token"
            )
        }
        var payload: [String: Any] = ["action": action]
        payload.merge(extra) { _, new in new }
        request.httpBody = try? JSONSerialization.data(withJSONObject: payload)
        URLSession.shared.dataTask(with: request).resume()
    }
}

/// The claim that hides Vox's status item, driven entirely by bin/bro-status-host
/// so the file format has exactly one owner and tests/run can prove it.
enum StatusHostClaim {
    @discardableResult
    static func run(_ arguments: [String]) -> Bool {
        let tool = BroPaths.statusHostTool
        guard FileManager.default.isExecutableFile(atPath: tool.path) else { return false }
        let task = Process()
        task.executableURL = tool
        task.arguments = arguments
        task.standardOutput = FileHandle.nullDevice
        task.standardError = FileHandle.nullDevice
        var environment = ProcessInfo.processInfo.environment
        environment["BRO_HOME"] = BroPaths.home.path
        task.environment = environment
        guard (try? task.run()) != nil else { return false }
        task.waitUntilExit()
        return task.terminationStatus == 0
    }

    static func claim() -> Bool {
        run(["claim", String(ProcessInfo.processInfo.processIdentifier)])
    }

    static func release() -> Bool {
        run(["release", String(ProcessInfo.processInfo.processIdentifier)])
    }
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

/// state/ first, then the legacy root path. `readWord` cannot tell "missing"
/// from "unreadable", so the fallback only fires when the primary truly has
/// nothing to say — which is exactly the mid-upgrade window.
func readWord(_ primary: URL, legacy: URL, fallback: String) -> String {
    if FileManager.default.fileExists(atPath: primary.path) {
        return readWord(primary, fallback: fallback)
    }
    return readWord(legacy, fallback: fallback)
}

// MARK: - Palette

/// Same mapping as bin/bro-status-paint. Keep the two in sync.
func color(for word: String) -> NSColor {
    switch word {
    case "starting", "working": return NSColor(hex: 0xe5c07b)
    case "speaking": return NSColor(hex: 0xc678dd)
    case "listening": return NSColor(hex: 0x61afef)
    case "down": return NSColor(hex: 0xe06c75)
    case "nudge": return NSColor(hex: 0xd19a66)
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
    /// The voice service, polled on the same timer as the status files.
    private let vox = VoxLink()
    /// Whether Vox's own status item is currently hidden in favour of this one.
    /// Flipped from the menu, so the full Vox panel is always one click away.
    private var claimingStatusBar = false
    /// Last rendered state. The status item is only touched when this changes,
    /// so the common case — nothing happening — costs a few small file reads.
    private struct Rendered: Equatable {
        var word: String
        var mode: String
        var queueDepth: Int
        var backend: String
        var nextReminder: String
        var vox: VoxSnapshot
    }
    private var rendered: Rendered?

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.target = self
        statusItem.button?.action = #selector(clicked)
        // Right-click has to reach the same action, or the voice controls that
        // used to live in Vox's popover would be unreachable.
        statusItem.button?.sendAction(on: [.leftMouseUp, .rightMouseUp])

        panel.start()
        registerHotKeys()
        // One icon in the menu bar: from here on Vox draws none.
        claimingStatusBar = StatusHostClaim.claim()

        refresh()
        let timer = Timer(timeInterval: 0.5, repeats: true) { [weak self] _ in self?.refresh() }
        // .common keeps polling alive while a menu-tracking loop is running.
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    private func refresh() {
        // The health answer lands a moment later and paints again; the file read
        // below is what keeps the word instant.
        vox.poll { [weak self] in self?.render() }
        render()
    }

    private func render() {
        let word = readWord(BroPaths.statusWord, legacy: BroPaths.statusWordLegacy, fallback: "ready")
        let mode = readWord(BroPaths.mode, legacy: BroPaths.modeLegacy, fallback: "call")
        let depth = queueDepth()
        let backend = readWord(BroPaths.backend, fallback: "")
        let reminder = readWord(BroPaths.nextReminder, fallback: "")
        let voice = vox.snapshot
        let next = Rendered(
            word: word, mode: mode, queueDepth: depth,
            backend: backend, nextReminder: reminder, vox: voice
        )
        if rendered == next { return }
        rendered = next

        guard let button = statusItem.button else { return }
        let title = NSMutableAttributedString(
            string: "● ",
            attributes: [
                .foregroundColor: color(for: word),
                .font: NSFont.systemFont(ofSize: 11),
            ]
        )
        title.append(NSAttributedString(
            string: prefix(for: mode) + word + queueSuffix(depth, word: word),
            attributes: [
                .foregroundColor: NSColor.labelColor,
                .font: NSFont.menuBarFont(ofSize: 0),
            ]
        ))
        button.attributedTitle = title
        button.image = voiceGlyph(voice)
        button.imagePosition = button.image == nil ? .noImage : .imageLeading
        button.toolTip = tooltip(
            word: word, mode: mode, depth: depth,
            backend: backend, reminder: reminder, vox: voice
        )
    }

    /// bin/bro-queue-count, counted in place: *.md files in inbox/pending.
    private func queueDepth() -> Int {
        guard let entries = try? FileManager.default.contentsOfDirectory(atPath: BroPaths.inboxPending.path)
        else { return 0 }
        return entries.filter { $0.hasSuffix(".md") }.count
    }

    /// "working ²" when asks are stacked behind the one in flight. Nothing when
    /// the queue is one deep — a single pending ask is the normal state.
    private func queueSuffix(_ depth: Int, word: String) -> String {
        guard word == "working", depth > 1 else { return "" }
        let superscripts = ["", "¹", "²", "³", "⁴", "⁵", "⁶", "⁷", "⁸", "⁹"]
        return " " + (depth <= 9 ? superscripts[depth] : "⁹⁺")
    }

    /// The last thing the backend log said, for a "down" tooltip. Reads at most
    /// the tail of the file, and only while the word is down.
    private func downCause() -> String {
        guard let handle = try? FileHandle(forReadingFrom: BroPaths.backendLog)
        else { return "" }
        defer { try? handle.close() }
        let end = handle.seekToEndOfFile()
        handle.seek(toFileOffset: end > 2048 ? end - 2048 : 0)
        let text = String(data: handle.readDataToEndOfFile(), encoding: .utf8) ?? ""
        return text.components(separatedBy: .newlines)
            .last { !$0.trimmingCharacters(in: .whitespaces).isEmpty }?
            .trimmingCharacters(in: .whitespaces) ?? ""
    }

    /// The half of Vox's icon that bro's word cannot say.
    ///
    /// Only those states get a glyph: "speaking", "working" and "ready" are
    /// already the word next to it, and drawing a symbol for them too would just
    /// say everything twice again. The live-mic red is copied from Vox exactly,
    /// pixels and all — see applyStatusGlyph in ~/vox-mcp/macos/VoxStatus.swift
    /// for why the colour is baked rather than left to the system to tint.
    private func voiceGlyph(_ vox: VoxSnapshot) -> NSImage? {
        let symbol: String
        var live = false
        if vox.bargeIn {
            symbol = "waveform.badge.mic"; live = true
        } else if vox.micOpen {
            symbol = "mic.fill"; live = true
        } else if !vox.reachable {
            // Nothing at all until Vox has been seen once: a machine without it
            // must not grow a permanent warning triangle.
            guard self.vox.everReachable else { return nil }
            symbol = "exclamationmark.triangle"
        } else {
            switch vox.state {
            case "paused": symbol = "pause.circle"
            case "off": symbol = "mic.slash.circle"
            case "error", "offline": symbol = "exclamationmark.triangle"
            default: return nil
            }
        }
        let darkMenuBar = UserDefaults.standard.string(forKey: "AppleInterfaceStyle")?
            .lowercased() == "dark"
        let glyphColor: NSColor = live ? .systemRed : (darkMenuBar ? .white : .black)
        let config = NSImage.SymbolConfiguration(pointSize: 12, weight: .semibold)
            .applying(NSImage.SymbolConfiguration(paletteColors: [glyphColor]))
        let image = NSImage(systemSymbolName: symbol, accessibilityDescription: symbol)?
            .withSymbolConfiguration(config)
        image?.isTemplate = false
        return image
    }

    /// Vox's tooltips, kept word for word where they were about the microphone —
    /// they are the sentence that tells you the mic is open and that a click
    /// closes it.
    private func tooltip(word: String, mode: String, depth: Int,
                         backend: String, reminder: String, vox: VoxSnapshot) -> String {
        let detail = voiceDetail(vox)
        let head: String
        if vox.bargeIn {
            head = "Mic is LIVE while Vox speaks — just start talking to interrupt."
        } else if vox.micOpen {
            head = "Mic is LIVE — click to stop listening."
        } else if word == "down" {
            let cause = downCause()
            head = cause.isEmpty
                ? "bro — backend is down. Run: bro doctor."
                : "bro — backend is down: \(cause)"
        } else if word == "working", depth > 1 {
            head = "bro — working, \(depth) asks queued."
        } else {
            head = "bro — \(prefix(for: mode))\(word). Click to open the panel."
        }
        var extras: [String] = []
        if !backend.isEmpty { extras.append("backend: \(backend)") }
        if !reminder.isEmpty { extras.append("next: \(reminder)") }
        let extraText = extras.isEmpty ? "" : " [\(extras.joined(separator: " · "))]"
        let voiceLine = detail.isEmpty ? "" : " \(detail)"
        return head + voiceLine + extraText + " Right-click for voice controls."
    }

    /// Vox's panelDetail(), which is what its tooltip appended.
    private func voiceDetail(_ vox: VoxSnapshot) -> String {
        if !vox.notesWaiting.isEmpty {
            let targets = vox.notesWaiting.map { $0 == "*" ? "any agent" : $0 }
                .joined(separator: ", ")
            return "Note waiting for: \(targets) — delivered on that agent's next turn."
        }
        if vox.state == "off", vox.lastStopReason == "idle_timeout" {
            return "Stopped after 10 minutes without activity. The microphone is closed."
        }
        if !vox.reachable {
            return self.vox.everReachable ? "Vox is offline." : ""
        }
        return vox.detail
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

    /// Vox's statusItemClicked, on bro's item.
    ///
    /// A left-click while the microphone is live ends the turn — it preserves
    /// what was said and sends it to transcription, unlike cancel. That was the
    /// fix for "I can stop talking but you can't stop listening", and it would
    /// have been the first thing lost by hiding Vox's icon. Everything else is
    /// bro's own wake, and a right-click opens the voice controls.
    @objc private func clicked() {
        let event = NSApp.currentEvent
        let rightClick = event?.type == .rightMouseUp
            || (event?.modifierFlags.contains(.control) ?? false)
        if rightClick {
            showVoiceMenu()
            return
        }
        if vox.snapshot.micOpen {
            vox.send("end_turn")
            return
        }
        panel.toggle()
    }

    /// What Vox's popover and its More… menu offered, as one menu. The panel's
    /// waveform is not reproduced here because it was never only in the panel:
    /// the floating HUD pill still draws it, and it is still Vox drawing it.
    private func showVoiceMenu() {
        let voice = vox.snapshot
        let menu = NSMenu()

        if voice.reachable {
            if voice.state == "speaking" {
                menu.addItem(item("Stop reading", #selector(voiceCancel)))
            }
            if voice.micOpen {
                menu.addItem(item("Stop listening — send what I said", #selector(voiceEndTurn)))
            }
            let reply = voice.lastSpokenAgent.isEmpty
                ? "Reply" : "Reply to \(voice.lastSpokenAgent)"
            let replyItem = item(reply, #selector(voiceReply))
            replyItem.isEnabled = voice.state == "idle" && !voice.micOpen
            menu.addItem(replyItem)
            menu.addItem(item("Repeat the last thing Vox said", #selector(voiceRepeat)))

            let modes = NSMenu()
            for (name, label) in [("talk", "Talk"), ("narrate", "Narrate"), ("dictate", "Dictate")] {
                let entry = item(label, #selector(voiceSetMode(_:)))
                entry.representedObject = name
                entry.state = voice.ioMode == name ? .on : .off
                modes.addItem(entry)
            }
            let modeItem = NSMenuItem(title: "Voice mode", action: nil, keyEquivalent: "")
            modeItem.submenu = modes
            menu.addItem(modeItem)

            let notes = NSMenu()
            for agent in voice.agents {
                let waiting = voice.notesWaiting.contains(agent)
                let entry = item(waiting ? "\(agent)   ● note waiting" : agent, #selector(voiceNote(_:)))
                entry.representedObject = agent
                notes.addItem(entry)
            }
            if !voice.agents.isEmpty { notes.addItem(NSMenuItem.separator()) }
            let anyAgent = item("Any agent (first to check)", #selector(voiceNote(_:)))
            anyAgent.representedObject = ""
            notes.addItem(anyAgent)
            let noteItem = NSMenuItem(title: "Leave a note for…", action: nil, keyEquivalent: "")
            noteItem.submenu = notes
            noteItem.isEnabled = voice.state == "idle"
            menu.addItem(noteItem)

            menu.addItem(NSMenuItem.separator())
            switch voice.state {
            case "off", "offline", "error":
                menu.addItem(item("Turn Vox on", #selector(voiceStart)))
            case "paused":
                menu.addItem(item("Resume Vox", #selector(voiceResume)))
            default:
                menu.addItem(item("Turn Vox off", #selector(voiceStop)))
            }
        } else {
            let dead = NSMenuItem(
                title: vox.everReachable ? "Vox is offline" : "Vox is not running",
                action: nil,
                keyEquivalent: ""
            )
            dead.isEnabled = false
            menu.addItem(dead)
        }

        menu.addItem(NSMenuItem.separator())
        // The escape hatch that makes hiding Vox's icon safe rather than final:
        // Vox's own item — and with it its panel, its restart control and
        // anything bro has not mirrored — is one click away, and comes back
        // within a second because the claim file is simply gone.
        menu.addItem(item(
            claimingStatusBar ? "Show Vox's own menu bar icon" : "Hide Vox's menu bar icon (bro shows it)",
            #selector(toggleStatusClaim)
        ))
        menu.addItem(item("Open the Vox folder", #selector(openVoxFolder)))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(item("Wake bro", #selector(wakeBroFromMenu)))

        for entry in menu.items where entry.action != nil { entry.target = self }
        // popUp, not statusItem.menu: assigning a menu would take the click away
        // from the action above, and the left-click end-turn would be gone.
        guard let button = statusItem.button else { return }
        menu.popUp(positioning: nil, at: NSPoint(x: 0, y: button.bounds.height + 4), in: button)
    }

    private func item(_ title: String, _ action: Selector) -> NSMenuItem {
        NSMenuItem(title: title, action: action, keyEquivalent: "")
    }

    @objc private func voiceCancel() { vox.send("cancel") }
    @objc private func voiceEndTurn() { vox.send("end_turn") }
    @objc private func voiceRepeat() { vox.send("repeat") }
    @objc private func voiceReply() { vox.send("reply") }
    @objc private func voiceStart() { vox.send("start") }
    @objc private func voiceResume() { vox.send("resume") }
    @objc private func voiceStop() { vox.send("stop") }

    @objc private func voiceSetMode(_ sender: NSMenuItem) {
        guard let mode = sender.representedObject as? String else { return }
        vox.send("set_mode", extra: ["mode": mode])
    }

    @objc private func voiceNote(_ sender: NSMenuItem) {
        let target = (sender.representedObject as? String) ?? ""
        vox.send("note", extra: target.isEmpty ? [:] : ["target_agent": target])
    }

    @objc private func toggleStatusClaim() {
        claimingStatusBar = claimingStatusBar
            ? !StatusHostClaim.release()
            : StatusHostClaim.claim()
    }

    @objc private func openVoxFolder() {
        NSWorkspace.shared.open(BroPaths.voxHome)
    }

    @objc private func wakeBroFromMenu() { wakeBro() }

    func applicationWillTerminate(_ notification: Notification) {
        // Best effort only. A SIGTERM or a crash never reaches this, which is
        // exactly why the claim carries a pid: Vox checks the claimant is alive.
        _ = StatusHostClaim.release()
    }

    private func wakeBro() {
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
