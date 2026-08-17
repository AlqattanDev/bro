// BroSummon — the typed half of the global summon.
//
// A one-line input that drops out of the top of the screen, takes the question,
// hands it to bin/bro-summon, and gives the keyboard straight back to whatever
// Ali was in.
//
// This is a SEPARATE window from macos/BroPanel.swift on purpose. The answer
// panel's guarantee is that it never takes focus — .nonactivatingPanel,
// canBecomeKey false, orderFrontRegardless, never activate(). A text field
// cannot be typed into under those rules: keystrokes only reach a window whose
// app is frontmost. So the two surfaces are split rather than compromised:
//
//   AnswerPanel  (BroPanel.swift)  never key, never main, never activates.
//   SummonPanel  (here)            key on purpose, and only while the field is
//                                  up — it records the frontmost app before it
//                                  opens and reactivates it on the way out.
//
// The focus Ali loses is the focus he spent by pressing the summon key, and he
// gets it back on Enter or Esc. Nothing bro decides to say on its own can take
// it.

import AppKit

extension BroPaths {
    static var summon: URL { home.appendingPathComponent("bin/bro-summon") }
}

/// Key-capable by design — see the file comment. Borderless windows are not
/// key-eligible unless they say so.
final class SummonPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override var canBecomeMain: Bool { false }
}

final class BroSummon: NSObject, NSTextFieldDelegate {
    private static let width: CGFloat = 560
    private static let height: CGFloat = 54

    private let panel: SummonPanel
    private let field = NSTextField()
    /// Whoever owned the keyboard when the field opened, so it can be handed
    /// back. Nil once returned, so a double dismiss cannot activate twice.
    private var previousApp: NSRunningApplication?
    private var open = false

    override init() {
        panel = SummonPanel(
            contentRect: NSRect(x: 0, y: 0, width: BroSummon.width, height: BroSummon.height),
            // .nonactivatingPanel still matters: BroBar stays an .accessory app
            // with no Dock icon, and the app-switcher order is left alone. The
            // activation below is explicit, scoped, and reversed on dismiss.
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        super.init()

        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.level = NSWindow.Level(rawValue: Int(CGShieldingWindowLevel()))
        panel.isMovable = false
        // Losing focus is a cancel: click away and the field is gone, rather
        // than left floating over the app Ali went back to.
        panel.hidesOnDeactivate = true
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]

        let blur = NSVisualEffectView()
        blur.material = .hudWindow
        blur.blendingMode = .behindWindow
        blur.state = .active
        blur.wantsLayer = true
        blur.layer?.cornerRadius = 14
        blur.layer?.cornerCurve = .continuous
        blur.layer?.masksToBounds = true
        blur.translatesAutoresizingMaskIntoConstraints = false

        let dot = NSTextField(labelWithString: "●")
        dot.font = NSFont.systemFont(ofSize: 12)
        dot.textColor = NSColor(hex: 0x7dcea0)
        dot.translatesAutoresizingMaskIntoConstraints = false

        field.isBordered = false
        field.drawsBackground = false
        field.focusRingType = .none
        field.font = NSFont.systemFont(ofSize: 17)
        field.textColor = .labelColor
        field.placeholderString = "ask bro…"
        field.delegate = self
        field.target = self
        field.action = #selector(submit)
        field.translatesAutoresizingMaskIntoConstraints = false

        let root = NSView(frame: NSRect(x: 0, y: 0, width: BroSummon.width, height: BroSummon.height))
        root.addSubview(blur)
        blur.addSubview(dot)
        blur.addSubview(field)
        NSLayoutConstraint.activate([
            blur.leadingAnchor.constraint(equalTo: root.leadingAnchor),
            blur.trailingAnchor.constraint(equalTo: root.trailingAnchor),
            blur.topAnchor.constraint(equalTo: root.topAnchor),
            blur.bottomAnchor.constraint(equalTo: root.bottomAnchor),
            dot.leadingAnchor.constraint(equalTo: blur.leadingAnchor, constant: 18),
            dot.centerYAnchor.constraint(equalTo: blur.centerYAnchor),
            field.leadingAnchor.constraint(equalTo: dot.trailingAnchor, constant: 12),
            field.trailingAnchor.constraint(equalTo: blur.trailingAnchor, constant: -18),
            field.centerYAnchor.constraint(equalTo: blur.centerYAnchor),
        ])
        panel.contentView = root

        // hidesOnDeactivate above pulls the window when Ali clicks away, but it
        // does not tell us. Without this the field would still believe it is
        // open and the next press of the hotkey would "do nothing" — it would
        // be toggling off a window that is already gone.
        NotificationCenter.default.addObserver(
            forName: NSApplication.didResignActiveNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            guard let self, self.open else { return }
            self.open = false
            self.field.stringValue = ""
            self.previousApp = nil
            self.panel.orderOut(nil)
        }
    }

    // MARK: Show / hide

    /// The hotkey is a toggle: pressing it again with the field up puts the
    /// keyboard back without asking anything.
    func toggle() {
        if open {
            dismiss()
        } else {
            show()
        }
    }

    private func show() {
        guard let screen = currentScreen() else { return }
        let visible = screen.visibleFrame
        panel.setFrame(
            NSRect(
                x: visible.midX - BroSummon.width / 2,
                y: visible.maxY - BroSummon.height - 120,
                width: BroSummon.width,
                height: BroSummon.height
            ),
            display: true
        )
        field.stringValue = ""
        // Remember before activating, or the frontmost app is us.
        previousApp = NSWorkspace.shared.frontmostApplication
        open = true
        NSApp.activate(ignoringOtherApps: true)
        panel.makeKeyAndOrderFront(nil)
        panel.makeFirstResponder(field)
    }

    private func dismiss() {
        guard open else { return }
        open = false
        field.stringValue = ""
        panel.orderOut(nil)
        // Hand the keyboard back to the app the summon interrupted. Without
        // this, dismissing would leave a Dock-less accessory app "active" and
        // Ali's next keystroke would go nowhere.
        let previous = previousApp
        previousApp = nil
        if let previous, previous.processIdentifier != ProcessInfo.processInfo.processIdentifier {
            previous.activate()
        } else {
            NSApp.hide(nil)
        }
    }

    private func currentScreen() -> NSScreen? {
        let pointer = NSEvent.mouseLocation
        return NSScreen.screens.first { $0.frame.contains(pointer) }
            ?? NSScreen.main
            ?? NSScreen.screens.first
    }

    // MARK: Submit

    @objc private func submit() {
        let text = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        // Dismiss first: the ask is asynchronous, so the keyboard should be
        // back in the other app before bro has even claimed the note.
        dismiss()
        guard !text.isEmpty else { return }
        BroSummon.run(["text", text])
    }

    /// Fire bin/bro-summon and forget it. Detached and unwaited for the same
    /// reason the menu bar click is: a hung script must not freeze the UI.
    static func run(_ arguments: [String]) {
        let tool = BroPaths.summon
        guard FileManager.default.isExecutableFile(atPath: tool.path) else { return }
        let task = Process()
        task.executableURL = tool
        task.arguments = arguments
        task.standardOutput = FileHandle.nullDevice
        task.standardError = FileHandle.nullDevice
        var environment = ProcessInfo.processInfo.environment
        environment["BRO_HOME"] = BroPaths.home.path
        task.environment = environment
        try? task.run()
    }

    // MARK: Keys

    func control(
        _ control: NSControl, textView: NSTextView, doCommandBy selector: Selector
    ) -> Bool {
        if selector == #selector(NSResponder.cancelOperation(_:)) {
            dismiss()
            return true
        }
        return false
    }
}
