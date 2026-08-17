// BroPanel — bro's answer surface, floating over every app.
//
// A non-activating NSPanel that renders ~/.bro/show/current.md as attributed
// text. It lives inside the BroBar process on purpose: one binary, one pidfile,
// one thing for bin/bro to start and stop, and the panel gets the same
// best-effort file reads the menu bar already uses.
//
// The load-bearing property is that it NEVER takes focus. A panel that grabs
// the keyboard while Ali is mid-sentence in another app is worse than the old
// tmux board, so: .nonactivatingPanel, canBecomeKey/canBecomeMain false,
// becomesKeyOnlyIfNeeded, orderFrontRegardless, and never
// activate(ignoringOtherApps:).
//
// Shell talks to it through a file, not a signal: bin/bro-show writes "open" or
// "closed" into ~/.bro/show/panel and the panel polls it. Same shape as every
// other bro control file, so it is testable from bash and survives the panel
// not running.

import AppKit
import ApplicationServices

extension BroPaths {
    static var showDir: URL { home.appendingPathComponent("show") }
    static var showCurrent: URL { showDir.appendingPathComponent("current.md") }
    /// "open" or "closed" — the toggle wire between bin/bro-show and the panel.
    static var showState: URL { showDir.appendingPathComponent("panel") }
}

// MARK: - Markdown

/// Render markdown well enough to read an answer: headings, bullets, quotes,
/// fenced code, and inline bold/italic/code. Block structure is handled here
/// line by line; inline spans go through Foundation's own markdown parser, so
/// there is no third-party dependency and no hand-rolled emphasis scanner.
enum BroMarkdown {
    private static let body = NSFont.systemFont(ofSize: 13)
    private static let mono = NSFont.monospacedSystemFont(ofSize: 12, weight: .regular)
    private static let codeColor = NSColor(hex: 0xe5c07b)
    private static let quoteColor = NSColor.secondaryLabelColor

    static func render(_ text: String) -> NSAttributedString {
        let out = NSMutableAttributedString()
        var inFence = false

        for line in text.components(separatedBy: .newlines) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)

            if trimmed.hasPrefix("```") {
                inFence.toggle()
                continue
            }
            if inFence {
                out.append(plain(line, font: mono, color: codeColor, indent: 12))
                continue
            }
            if trimmed.isEmpty {
                out.append(NSAttributedString(string: "\n"))
                continue
            }
            if let (level, rest) = heading(trimmed) {
                let size: CGFloat = level == 1 ? 18 : (level == 2 ? 15 : 13.5)
                out.append(inline(
                    rest,
                    font: NSFont.systemFont(ofSize: size, weight: .semibold),
                    color: .labelColor,
                    spaceAbove: out.length == 0 ? 0 : 8
                ))
                continue
            }
            if let rest = bullet(trimmed) {
                out.append(inline("•  " + rest, font: body, color: .labelColor, indent: 14))
                continue
            }
            if trimmed.hasPrefix("> ") {
                out.append(inline(
                    String(trimmed.dropFirst(2)),
                    font: body, color: quoteColor, indent: 14
                ))
                continue
            }
            out.append(inline(trimmed, font: body, color: .labelColor))
        }
        return out
    }

    private static func heading(_ line: String) -> (Int, String)? {
        var level = 0
        var rest = Substring(line)
        while rest.first == "#", level < 6 {
            level += 1
            rest = rest.dropFirst()
        }
        guard level > 0, rest.first == " " else { return nil }
        return (level, rest.trimmingCharacters(in: .whitespaces))
    }

    private static func bullet(_ line: String) -> String? {
        for marker in ["- ", "* ", "+ "] where line.hasPrefix(marker) {
            return String(line.dropFirst(marker.count))
        }
        // "1. " style, without pulling in a regex.
        let digits = line.prefix { $0.isNumber }
        if !digits.isEmpty, line.dropFirst(digits.count).hasPrefix(". ") {
            return digits + ". " + line.dropFirst(digits.count + 2)
        }
        return nil
    }

    private static func paragraph(indent: CGFloat, spaceAbove: CGFloat) -> NSParagraphStyle {
        let style = NSMutableParagraphStyle()
        style.lineSpacing = 2
        style.paragraphSpacingBefore = spaceAbove
        style.firstLineHeadIndent = 0
        style.headIndent = indent
        return style
    }

    private static func plain(
        _ line: String, font: NSFont, color: NSColor,
        indent: CGFloat = 0, spaceAbove: CGFloat = 0
    ) -> NSAttributedString {
        NSAttributedString(
            string: line + "\n",
            attributes: [
                .font: font,
                .foregroundColor: color,
                .paragraphStyle: paragraph(indent: indent, spaceAbove: spaceAbove),
            ]
        )
    }

    /// One block line with its inline markdown resolved into real fonts.
    private static func inline(
        _ line: String, font: NSFont, color: NSColor,
        indent: CGFloat = 0, spaceAbove: CGFloat = 0
    ) -> NSAttributedString {
        guard let parsed = try? NSAttributedString(
            markdown: line,
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        ) else {
            return plain(line, font: font, color: color, indent: indent, spaceAbove: spaceAbove)
        }

        let out = NSMutableAttributedString(attributedString: parsed)
        let whole = NSRange(location: 0, length: out.length)
        out.addAttributes(
            [
                .font: font,
                .foregroundColor: color,
                .paragraphStyle: paragraph(indent: indent, spaceAbove: spaceAbove),
            ],
            range: whole
        )
        // Foundation records emphasis as an intent, not as a font. Turn the
        // intents it found into the fonts a reader actually sees.
        out.enumerateAttribute(.inlinePresentationIntent, in: whole) { value, range, _ in
            guard let raw = value as? Int else { return }
            let intent = InlinePresentationIntent(rawValue: UInt(raw))
            if intent.contains(.code) {
                out.addAttributes([.font: mono, .foregroundColor: codeColor], range: range)
                return
            }
            var traits: NSFontTraitMask = []
            if intent.contains(.stronglyEmphasized) { traits.insert(.boldFontMask) }
            if intent.contains(.emphasized) { traits.insert(.italicFontMask) }
            guard !traits.isEmpty else { return }
            let styled = NSFontManager.shared.convert(font, toHaveTrait: traits)
            out.addAttribute(.font, value: styled, range: range)
        }
        out.append(NSAttributedString(string: "\n", attributes: [.font: font]))
        return out
    }
}

// MARK: - Panel

/// Never key, never main. Ordering this in front must not move the keyboard.
final class AnswerPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

final class BroPanel {
    /// Top-right, tucked under the menu bar: out of the way of whatever is
    /// being read or typed, and the same corner every time so it is findable.
    private static let width: CGFloat = 520
    private static let inset: CGFloat = 16
    private static let minHeight: CGFloat = 90
    private static let footerHeight: CGFloat = 40

    private let panel: AnswerPanel
    private let scroll = NSScrollView()
    private let textView = NSTextView()
    private let talkButton = NSButton(title: "Talk", target: nil, action: nil)
    private var timer: Timer?
    private var escMonitors: [Any] = []
    /// Last (state, content stamp) acted on, so the poll costs one stat call
    /// when nothing has changed.
    private var shownState = false
    private var loadedStamp: Date?

    init() {
        panel = AnswerPanel(
            contentRect: NSRect(x: 0, y: 0, width: BroPanel.width, height: 240),
            // .nonactivatingPanel is the whole point: without it, showing the
            // panel activates BroBar and the app Ali is typing in loses focus.
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        // Float over full-screen apps too — a full-screen terminal or browser
        // is exactly where an answer needs to be visible.
        panel.level = NSWindow.Level(rawValue: Int(CGShieldingWindowLevel()))
        panel.isMovable = false
        panel.hidesOnDeactivate = false
        panel.becomesKeyOnlyIfNeeded = true
        panel.collectionBehavior = [
            .canJoinAllSpaces, .stationary, .fullScreenAuxiliary, .ignoresCycle,
        ]

        let blur = NSVisualEffectView()
        blur.material = .hudWindow
        blur.blendingMode = .behindWindow
        blur.state = .active
        blur.wantsLayer = true
        blur.layer?.cornerRadius = 14
        blur.layer?.cornerCurve = .continuous
        blur.layer?.masksToBounds = true
        blur.translatesAutoresizingMaskIntoConstraints = false

        textView.isEditable = false
        // Not selectable on purpose: selection needs key focus, and a click
        // anywhere on the panel is the dismiss gesture.
        textView.isSelectable = false
        textView.drawsBackground = false
        textView.textContainerInset = NSSize(width: 16, height: 14)
        textView.textContainer?.widthTracksTextView = true

        scroll.documentView = textView
        scroll.drawsBackground = false
        scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true
        scroll.translatesAutoresizingMaskIntoConstraints = false

        talkButton.bezelStyle = .rounded
        talkButton.font = NSFont.systemFont(ofSize: 12, weight: .medium)
        talkButton.target = self
        talkButton.action = #selector(talk)
        talkButton.refusesFirstResponder = true
        talkButton.toolTip = "Open the mic"
        talkButton.translatesAutoresizingMaskIntoConstraints = false

        let footer = NSView()
        footer.translatesAutoresizingMaskIntoConstraints = false
        footer.addSubview(talkButton)

        blur.addSubview(scroll)
        blur.addSubview(footer)
        // Dismiss is the text, not the whole card — Talk has to stay clickable.
        let click = NSClickGestureRecognizer(target: self, action: #selector(clicked))
        scroll.addGestureRecognizer(click)

        let root = NSView()
        root.addSubview(blur)
        blur.translatesAutoresizingMaskIntoConstraints = false
        root.translatesAutoresizingMaskIntoConstraints = true
        NSLayoutConstraint.activate([
            blur.leadingAnchor.constraint(equalTo: root.leadingAnchor),
            blur.trailingAnchor.constraint(equalTo: root.trailingAnchor),
            blur.topAnchor.constraint(equalTo: root.topAnchor),
            blur.bottomAnchor.constraint(equalTo: root.bottomAnchor),
            scroll.leadingAnchor.constraint(equalTo: blur.leadingAnchor),
            scroll.trailingAnchor.constraint(equalTo: blur.trailingAnchor),
            scroll.topAnchor.constraint(equalTo: blur.topAnchor),
            scroll.bottomAnchor.constraint(equalTo: footer.topAnchor),
            footer.leadingAnchor.constraint(equalTo: blur.leadingAnchor),
            footer.trailingAnchor.constraint(equalTo: blur.trailingAnchor),
            footer.bottomAnchor.constraint(equalTo: blur.bottomAnchor),
            footer.heightAnchor.constraint(equalToConstant: BroPanel.footerHeight),
            talkButton.leadingAnchor.constraint(equalTo: footer.leadingAnchor, constant: 12),
            talkButton.centerYAnchor.constraint(equalTo: footer.centerYAnchor),
        ])
        panel.contentView = root
        panel.alphaValue = 0
    }

    /// Menu-bar click. Writes the same file `bro-show --toggle` does, so the
    /// poll — not a second show path — is what puts the panel on screen.
    func toggle() {
        try? FileManager.default.createDirectory(
            at: BroPaths.showDir, withIntermediateDirectories: true
        )
        let next = shownState ? "closed\n" : "open\n"
        try? next.write(to: BroPaths.showState, atomically: true, encoding: .utf8)
    }

    func start() {
        installEscape()
        poll()
        let timer = Timer(timeInterval: 0.2, repeats: true) { [weak self] _ in self?.poll() }
        RunLoop.main.add(timer, forMode: .common)
        self.timer = timer
    }

    // MARK: Poll

    private func poll() {
        let want = readWord(BroPaths.showState, fallback: "closed") == "open"
        if want {
            reloadIfChanged()
            if !shownState { show() }
        } else if shownState {
            hide()
        }
    }

    private func reloadIfChanged() {
        let stamp = (try? FileManager.default.attributesOfItem(atPath: BroPaths.showCurrent.path))
            .flatMap { $0[.modificationDate] as? Date }
        if let stamp, stamp == loadedStamp { return }
        loadedStamp = stamp

        let raw = (try? String(contentsOf: BroPaths.showCurrent, encoding: .utf8))
            ?? "(nothing to show)"
        textView.textStorage?.setAttributedString(BroMarkdown.render(raw))
        textView.scroll(NSPoint(x: 0, y: 0))
        resize()
    }

    /// Height follows the text, up to two-thirds of the screen; past that the
    /// scroll view takes over.
    private func resize() {
        guard let screen = currentScreen() else { return }
        let visible = screen.visibleFrame
        let usable = BroPanel.width - 32
        textView.frame = NSRect(x: 0, y: 0, width: BroPanel.width, height: 10)
        textView.textContainer?.containerSize = NSSize(
            width: usable, height: .greatestFiniteMagnitude
        )
        var height = BroPanel.minHeight
        if let layout = textView.layoutManager, let container = textView.textContainer {
            layout.ensureLayout(for: container)
            height = layout.usedRect(for: container).height + 30
        }
        height = min(max(height, BroPanel.minHeight), visible.height * 0.66)
        height += BroPanel.footerHeight
        panel.setFrame(
            NSRect(
                x: visible.maxX - BroPanel.width - BroPanel.inset,
                y: visible.maxY - height - BroPanel.inset,
                width: BroPanel.width,
                height: height
            ),
            display: true
        )
    }

    private func currentScreen() -> NSScreen? {
        let pointer = NSEvent.mouseLocation
        return NSScreen.screens.first { $0.frame.contains(pointer) }
            ?? NSScreen.main
            ?? NSScreen.screens.first
    }

    // MARK: Show / hide

    private func show() {
        shownState = true
        resize()
        // orderFrontRegardless, never makeKeyAndOrderFront and never
        // activate(ignoringOtherApps:): the panel appears without BroBar
        // becoming the active application.
        panel.orderFrontRegardless()
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.12
            panel.animator().alphaValue = 1
        }
    }

    private func hide() {
        shownState = false
        NSAnimationContext.runAnimationGroup({ context in
            context.duration = 0.12
            panel.animator().alphaValue = 0
        }, completionHandler: { [panel] in
            if panel.alphaValue == 0 { panel.orderOut(nil) }
        })
    }

    /// Dismiss and tell the shell, so `bro-show --toggle` agrees with what is
    /// actually on screen.
    private func dismiss() {
        guard shownState else { return }
        hide()
        try? FileManager.default.createDirectory(
            at: BroPaths.showDir, withIntermediateDirectories: true
        )
        try? "closed\n".write(to: BroPaths.showState, atomically: true, encoding: .utf8)
    }

    @objc private func clicked() {
        dismiss()
    }

    @objc private func talk() {
        BroSummon.run(["voice"])
    }

    /// Esc. A borderless non-key panel never receives keystrokes itself, so the
    /// only way to see Esc while another app has focus is a global monitor,
    /// which macOS only delivers to a process trusted for Accessibility. We do
    /// not prompt for that permission — if it was never granted, Esc simply
    /// does nothing and the click and F1 paths still dismiss.
    private func installEscape() {
        let handler: (NSEvent) -> Void = { [weak self] event in
            guard event.keyCode == 53 else { return }  // Esc
            self?.dismiss()
        }
        if AXIsProcessTrusted(),
           let global = NSEvent.addGlobalMonitorForEvents(matching: .keyDown, handler: handler)
        {
            escMonitors.append(global)
        }
        if let local = NSEvent.addLocalMonitorForEvents(matching: .keyDown, handler: { event in
            handler(event)
            return event
        }) {
            escMonitors.append(local)
        }
    }
}
