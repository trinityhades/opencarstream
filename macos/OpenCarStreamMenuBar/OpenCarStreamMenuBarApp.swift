import AppKit
import SwiftUI

@main
struct OpenCarStreamMenuBarApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    var body: some Scene {
        Settings {
            SettingsView()
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private var serverProcess: Process?

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.title = "OCS"
        rebuildMenu()
    }

    private func rebuildMenu() {
        let menu = NSMenu()
        let running = serverProcess?.isRunning == true

        let toggleTitle = running ? "Stop Server" : "Start Server"
        menu.addItem(NSMenuItem(title: toggleTitle, action: #selector(toggleServer), keyEquivalent: "s"))
        menu.addItem(NSMenuItem(title: "Open Dashboard", action: #selector(openDashboard), keyEquivalent: "o"))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Settings...", action: #selector(openSettings), keyEquivalent: ","))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(NSMenuItem(title: "Quit", action: #selector(quit), keyEquivalent: "q"))

        for item in menu.items {
            item.target = self
        }
        statusItem.menu = menu
        statusItem.button?.title = running ? "OCS On" : "OCS"
    }

    @objc private func toggleServer() {
        if serverProcess?.isRunning == true {
            serverProcess?.terminate()
            serverProcess = nil
            rebuildMenu()
            return
        }

        let defaults = UserDefaults.standard
        let cliPath = defaults.string(forKey: "cliPath") ?? "/opt/homebrew/bin/opencarstream"
        let port = defaults.string(forKey: "port") ?? "33333"
        let configDir = defaults.string(forKey: "configDir") ?? "\(NSHomeDirectory())/Library/Application Support/OpenCarStream"
        let mediaDir = defaults.string(forKey: "mediaDir") ?? "\(NSHomeDirectory())/Movies"
        let iptvDir = defaults.string(forKey: "iptvDir") ?? "\(NSHomeDirectory())/Library/Application Support/OpenCarStream/iptv_lists"

        try? FileManager.default.createDirectory(atPath: configDir, withIntermediateDirectories: true)
        try? FileManager.default.createDirectory(atPath: iptvDir, withIntermediateDirectories: true)

        let process = Process()
        process.executableURL = URL(fileURLWithPath: cliPath)
        process.arguments = [
            "serve",
            "--host", "0.0.0.0",
            "--port", port,
            "--config-dir", configDir,
            "--local-media-dir", mediaDir,
            "--iptv-lists-dir", iptvDir,
        ]
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                self?.serverProcess = nil
                self?.rebuildMenu()
            }
        }

        do {
            try process.run()
            serverProcess = process
        } catch {
            showAlert("Could not start OpenCarStream", detail: error.localizedDescription)
        }
        rebuildMenu()
    }

    @objc private func openDashboard() {
        let port = UserDefaults.standard.string(forKey: "port") ?? "33333"
        if let url = URL(string: "http://127.0.0.1:\(port)/") {
            NSWorkspace.shared.open(url)
        }
    }

    @objc private func openSettings() {
        NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)
    }

    @objc private func quit() {
        serverProcess?.terminate()
        NSApp.terminate(nil)
    }

    private func showAlert(_ message: String, detail: String) {
        let alert = NSAlert()
        alert.messageText = message
        alert.informativeText = detail
        alert.alertStyle = .warning
        alert.runModal()
    }
}

struct SettingsView: View {
    @AppStorage("cliPath") private var cliPath = "/opt/homebrew/bin/opencarstream"
    @AppStorage("port") private var port = "33333"
    @AppStorage("configDir") private var configDir = "\(NSHomeDirectory())/Library/Application Support/OpenCarStream"
    @AppStorage("mediaDir") private var mediaDir = "\(NSHomeDirectory())/Movies"
    @AppStorage("iptvDir") private var iptvDir = "\(NSHomeDirectory())/Library/Application Support/OpenCarStream/iptv_lists"

    var body: some View {
        Form {
            TextField("CLI path", text: $cliPath)
            TextField("Port", text: $port)
            TextField("Config directory", text: $configDir)
            TextField("Local media directory", text: $mediaDir)
            TextField("IPTV lists directory", text: $iptvDir)
        }
        .padding(20)
        .frame(width: 520)
    }
}
