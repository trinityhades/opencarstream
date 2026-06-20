import AppKit
import Darwin
import SwiftUI

private enum DefaultsKey {
    static let cliPath = "cliPath"
    static let host = "host"
    static let port = "port"
    static let adminPassword = "adminPassword"
    static let configDir = "configDir"
    static let mediaDir = "mediaDir"
    static let iptvDir = "iptvDir"
    static let autoOpenDashboard = "autoOpenDashboard"
}

private struct AppDefaults {
    static let appSupportDir = "\(NSHomeDirectory())/Library/Application Support/OpenCarStream"
    static let defaultConfigDir = "\(appSupportDir)/config"

    static func register() {
        UserDefaults.standard.register(defaults: [
            DefaultsKey.cliPath: defaultCLIPath(),
            DefaultsKey.host: "0.0.0.0",
            DefaultsKey.port: "33333",
            DefaultsKey.adminPassword: "admin",
            DefaultsKey.configDir: defaultConfigDir,
            DefaultsKey.mediaDir: "\(NSHomeDirectory())/Movies",
            DefaultsKey.iptvDir: "\(appSupportDir)/iptv_lists",
            DefaultsKey.autoOpenDashboard: false,
        ])
    }

    static func defaultCLIPath() -> String {
        let candidates = [
            "/opt/homebrew/bin/opencarstream",
            "/usr/local/bin/opencarstream",
            "/usr/local/bin/opencarstream-cli",
        ]
        return candidates.first { FileManager.default.isExecutableFile(atPath: $0) } ?? candidates[0]
    }
}

@main
struct OpenCarStreamMenuBarApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    init() {
        AppDefaults.register()
    }

    var body: some Scene {
        Settings {
            SettingsView()
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private var serverProcess: Process?
    private var healthTimer: Timer?
    private var lastHealth = "Stopped"
    private var isTerminatingApp = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.image = NSImage(systemSymbolName: "car.fill", accessibilityDescription: "OpenCarStream")
        statusItem.button?.imagePosition = .imageLeading
        rebuildMenu()
        startHealthTimer()
    }

    func applicationWillTerminate(_ notification: Notification) {
        stopServer()
    }

    private var dashboardURL: URL? {
        let port = UserDefaults.standard.string(forKey: DefaultsKey.port) ?? "33333"
        return URL(string: "http://127.0.0.1:\(port)/")
    }

    private var logURL: URL {
        let configDir = resolvedConfigDir(UserDefaults.standard.string(forKey: DefaultsKey.configDir))
        return URL(fileURLWithPath: configDir).appendingPathComponent("opencarstream.log")
    }

    private func resolvedConfigDir(_ rawPath: String?) -> String {
        let raw = (rawPath?.isEmpty == false) ? rawPath! : AppDefaults.defaultConfigDir
        let expanded = (raw as NSString).expandingTildeInPath
        if URL(fileURLWithPath: expanded).lastPathComponent == "config" {
            return expanded
        }
        let nested = (expanded as NSString).appendingPathComponent("config")
        if expanded == AppDefaults.appSupportDir || FileManager.default.fileExists(atPath: nested) {
            return nested
        }
        return expanded
    }

    private func rebuildMenu() {
        let running = serverProcess?.isRunning == true
        let menu = NSMenu()

        let status = NSMenuItem(title: "Status: \(running ? lastHealth : "Stopped")", action: nil, keyEquivalent: "")
        status.isEnabled = false
        menu.addItem(status)
        menu.addItem(NSMenuItem.separator())

        menu.addItem(menuItem(running ? "Stop Server" : "Start Server", #selector(toggleServer), "s"))
        menu.addItem(menuItem("Restart Server", #selector(restartServer), "r", enabled: running))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(menuItem("Open Dashboard", #selector(openDashboard), "o"))
        menu.addItem(menuItem("Open Config Folder", #selector(openConfigFolder), ""))
        menu.addItem(menuItem("Open Log", #selector(openLog), "l"))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(menuItem("Settings...", #selector(openSettings), ","))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(menuItem("Quit", #selector(quit), "q"))

        statusItem.menu = menu
        statusItem.button?.title = running ? "On" : ""
    }

    private func menuItem(_ title: String, _ action: Selector, _ key: String, enabled: Bool = true) -> NSMenuItem {
        let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
        item.target = self
        item.isEnabled = enabled
        return item
    }

    private func startHealthTimer() {
        healthTimer?.invalidate()
        healthTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            self?.refreshHealth()
        }
    }

    private func refreshHealth() {
        guard serverProcess?.isRunning == true, let url = dashboardURL?.appendingPathComponent("health") else {
            lastHealth = "Stopped"
            rebuildMenu()
            return
        }

        URLSession.shared.dataTask(with: url) { [weak self] data, _, _ in
            let nextHealth: String
            if let data, let text = String(data: data, encoding: .utf8), text.contains("\"ok\": true") {
                nextHealth = "Running"
            } else {
                nextHealth = "Starting"
            }
            DispatchQueue.main.async {
                self?.lastHealth = nextHealth
                self?.rebuildMenu()
            }
        }.resume()
    }

    @objc private func toggleServer() {
        if serverProcess?.isRunning == true {
            stopServer()
        } else {
            startServer()
        }
    }

    @objc private func restartServer() {
        stopServer()
        startServer()
    }

    private func startServer() {
        let defaults = UserDefaults.standard
        let cliPath = defaults.string(forKey: DefaultsKey.cliPath) ?? AppDefaults.defaultCLIPath()
        guard FileManager.default.isExecutableFile(atPath: cliPath) else {
            showAlert(
                "OpenCarStream CLI not found",
                detail: "Install the CLI with Homebrew, or set the CLI path in Settings."
            )
            return
        }

        let host = defaults.string(forKey: DefaultsKey.host) ?? "0.0.0.0"
        let port = defaults.string(forKey: DefaultsKey.port) ?? "33333"
        let adminPassword = defaults.string(forKey: DefaultsKey.adminPassword) ?? "admin"
        let configDir = resolvedConfigDir(defaults.string(forKey: DefaultsKey.configDir))
        let mediaDir = ((defaults.string(forKey: DefaultsKey.mediaDir) ?? "\(NSHomeDirectory())/Movies") as NSString).expandingTildeInPath
        let iptvDir = ((defaults.string(forKey: DefaultsKey.iptvDir) ?? "\(AppDefaults.appSupportDir)/iptv_lists") as NSString).expandingTildeInPath

        createDirectory(configDir)
        createDirectory(mediaDir)
        createDirectory(iptvDir)

        let process = Process()
        process.executableURL = URL(fileURLWithPath: cliPath)
        process.arguments = [
            "serve",
            "--host", host,
            "--port", port,
            "--admin-password", adminPassword,
            "--config-dir", configDir,
            "--local-media-dir", mediaDir,
            "--iptv-lists-dir", iptvDir,
        ]
        process.environment = [
            "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        ]

        let logHandle = openLogHandle()
        process.standardOutput = logHandle
        process.standardError = logHandle
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                self?.serverProcess = nil
                self?.lastHealth = "Stopped"
                if self?.isTerminatingApp != true {
                    self?.rebuildMenu()
                }
            }
        }

        do {
            try process.run()
            serverProcess = process
            lastHealth = "Starting"
            rebuildMenu()
            refreshHealth()
            if defaults.bool(forKey: DefaultsKey.autoOpenDashboard) {
                openDashboard()
            }
        } catch {
            showAlert("Could not start OpenCarStream", detail: error.localizedDescription)
        }
    }

    private func stopServer() {
        let process = serverProcess
        serverProcess = nil
        lastHealth = "Stopped"
        if !isTerminatingApp {
            rebuildMenu()
        }

        guard let process, process.isRunning else {
            return
        }

        process.terminate()
        let pid = process.processIdentifier
        DispatchQueue.global().asyncAfter(deadline: .now() + 2) {
            if process.isRunning {
                kill(pid, SIGKILL)
            }
        }
    }

    private func openLogHandle() -> FileHandle {
        let url = logURL
        createDirectory(url.deletingLastPathComponent().path)
        if !FileManager.default.fileExists(atPath: url.path) {
            FileManager.default.createFile(atPath: url.path, contents: nil)
        }
        let handle = try? FileHandle(forWritingTo: url)
        handle?.seekToEndOfFile()
        return handle ?? FileHandle.standardError
    }

    private func createDirectory(_ path: String) {
        try? FileManager.default.createDirectory(atPath: path, withIntermediateDirectories: true)
    }

    @objc private func openDashboard() {
        if let dashboardURL {
            NSWorkspace.shared.open(dashboardURL)
        }
    }

    @objc private func openConfigFolder() {
        let configDir = resolvedConfigDir(UserDefaults.standard.string(forKey: DefaultsKey.configDir))
        NSWorkspace.shared.open(URL(fileURLWithPath: configDir))
    }

    @objc private func openLog() {
        NSWorkspace.shared.open(logURL)
    }

    @objc private func openSettings() {
        NSApp.activate(ignoringOtherApps: true)
        NSApp.sendAction(Selector(("showSettingsWindow:")), to: nil, from: nil)
    }

    @objc private func quit() {
        isTerminatingApp = true
        healthTimer?.invalidate()
        healthTimer = nil
        stopServer()
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
    @AppStorage(DefaultsKey.cliPath) private var cliPath = AppDefaults.defaultCLIPath()
    @AppStorage(DefaultsKey.host) private var host = "0.0.0.0"
    @AppStorage(DefaultsKey.port) private var port = "33333"
    @AppStorage(DefaultsKey.adminPassword) private var adminPassword = "admin"
    @AppStorage(DefaultsKey.configDir) private var configDir = AppDefaults.defaultConfigDir
    @AppStorage(DefaultsKey.mediaDir) private var mediaDir = "\(NSHomeDirectory())/Movies"
    @AppStorage(DefaultsKey.iptvDir) private var iptvDir = "\(AppDefaults.appSupportDir)/iptv_lists"
    @AppStorage(DefaultsKey.autoOpenDashboard) private var autoOpenDashboard = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("OpenCarStream")
                .font(.title2.weight(.semibold))

            Form {
                TextField("CLI path", text: $cliPath)
                TextField("Host", text: $host)
                TextField("Port", text: $port)
                SecureField("Admin password", text: $adminPassword)
                TextField("Config directory", text: $configDir)
                TextField("Local media directory", text: $mediaDir)
                TextField("IPTV lists directory", text: $iptvDir)
                Toggle("Open dashboard after starting", isOn: $autoOpenDashboard)
            }
        }
        .padding(20)
        .frame(width: 560)
    }
}
