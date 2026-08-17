// Entry point for BroBar: the menu bar face (macos/BroBar.swift) plus the
// floating answer panel (macos/BroPanel.swift), one process.
//
// .accessory activation policy: no Dock icon, and — with the panel's
// .nonactivatingPanel — nothing here ever becomes the active application.

import AppKit

let app = NSApplication.shared
let delegate = BroBar()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
