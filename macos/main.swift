// Entry point for BroBar: the menu bar face (macos/BroBar.swift) plus the
// floating answer panel (macos/BroPanel.swift), one process.
//
// .accessory activation policy: no Dock icon, and — with the panel's
// .nonactivatingPanel — nothing here ever becomes the active application.

import AppKit

let app = NSApplication.shared
// One face in the menu bar. `bro` and the launchd daemon both start BroBar;
// without this, two copies sit next to each other and say the same thing.
let others = NSWorkspace.shared.runningApplications.filter {
    $0.bundleIdentifier == "com.bro.brobar"
        && $0.processIdentifier != ProcessInfo.processInfo.processIdentifier
}
if !others.isEmpty { exit(0) }
let delegate = BroBar()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
