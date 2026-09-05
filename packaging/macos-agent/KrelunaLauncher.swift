import Cocoa
import ScreenCaptureKit

// Invoked only by the authenticated remote-session worker. No listening port,
// files, or frame logging: the native app returns one frame through stdout.
@available(macOS 14.0, *)
func captureNativeFrame() async throws -> [String: Any] {
    guard CGPreflightScreenCaptureAccess() || CGRequestScreenCaptureAccess() else {
        return ["error": "Autorizza Kreluna Agent in Registrazione schermo, poi riavvia l’Agent."]
    }
    let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
    guard let display = content.displays.first(where: { $0.displayID == CGMainDisplayID() }) else {
        return ["error": "Schermo principale non disponibile"]
    }
    let bounds = CGDisplayBounds(display.displayID)
    let scale = min(1.0, min(1440.0 / bounds.width, 1000.0 / bounds.height))
    let configuration = SCStreamConfiguration()
    configuration.width = max(1, Int(bounds.width * scale))
    configuration.height = max(1, Int(bounds.height * scale))
    configuration.showsCursor = true
    let filter = SCContentFilter(display: display, excludingWindows: [])
    let cgImage = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: configuration)
    let bitmap = NSBitmapImageRep(cgImage: cgImage)
    guard let jpeg = bitmap.representation(using: .jpeg, properties: [.compressionFactor: 0.65]) else {
        return ["error": "Immagine non disponibile"]
    }
    return ["image": jpeg.base64EncodedString(), "width": bounds.width, "height": bounds.height]
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var agentProcess: Process?
    private var guideProcess: Process?

    func applicationDidFinishLaunching(_ notification: Notification) {
        startAgent()
    }

    func applicationShouldHandleReopen(
        _ sender: NSApplication,
        hasVisibleWindows flag: Bool
    ) -> Bool {
        startGuide()
        sender.activate(ignoringOtherApps: true)
        return true
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let process = agentProcess, process.isRunning {
            process.terminate()
        }
        if let process = guideProcess, process.isRunning {
            process.terminate()
        }
    }

    private func configuredProcess(guideOnly: Bool) -> Process? {
        guard
            let resources = Bundle.main.resourceURL,
            let support = FileManager.default.urls(
                for: .applicationSupportDirectory,
                in: .userDomainMask
            ).first
        else { return nil }

        let appRoot = resources.appendingPathComponent("app")
        let pythonHome = resources.appendingPathComponent("python-arm64")
        let python = pythonHome.appendingPathComponent("bin/python3.12")
        let dataRoot = support.appendingPathComponent("KrelunaAgent")
        try? FileManager.default.createDirectory(
            at: dataRoot.appendingPathComponent("data"),
            withIntermediateDirectories: true
        )

        var environment = ProcessInfo.processInfo.environment
        environment["PYTHONHOME"] = pythonHome.path
        environment["PYTHONPATH"] = [
            appRoot.appendingPathComponent("packages/kreluna-shared/src").path,
            appRoot.appendingPathComponent("apps/kreluna-agent").path,
        ].joined(separator: ":")
        environment["KRELUNA_AGENT_DATA_DIR"] = dataRoot.appendingPathComponent("data").path
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["KRELUNA_TRUST_SAVED_CONFIG"] = "1"
        environment["KRELUNA_NATIVE_CAPTURE"] = Bundle.main.executableURL?.path
        if guideOnly {
            environment["KRELUNA_GUIDE_ONLY"] = "1"
        }

        let directorURL = resources.appendingPathComponent("director.url")
        if let value = try? String(contentsOf: directorURL, encoding: .utf8)
            .trimmingCharacters(in: .whitespacesAndNewlines), !value.isEmpty {
            environment["AGENT_DIRECTOR_URL"] = value
        }

        let process = Process()
        process.executableURL = python
        process.arguments = ["-m", "agent.mac_boot"]
        process.currentDirectoryURL = appRoot
        process.environment = environment

        let logURL = dataRoot.appendingPathComponent("kreluna-agent.log")
        if !FileManager.default.fileExists(atPath: logURL.path) {
            FileManager.default.createFile(atPath: logURL.path, contents: nil)
        }
        if let log = try? FileHandle(forWritingTo: logURL) {
            _ = try? log.seekToEnd()
            process.standardOutput = log
            process.standardError = log
            process.terminationHandler = { _ in try? log.close() }
        }
        return process
    }

    private func startAgent() {
        guard agentProcess?.isRunning != true,
              let process = configuredProcess(guideOnly: false) else { return }
        do {
            try process.run()
            agentProcess = process
        } catch {
            showError("Kreluna Agent non è riuscito ad avviarsi.")
        }
    }

    private func startGuide() {
        guard guideProcess?.isRunning != true,
              let process = configuredProcess(guideOnly: true) else { return }
        do {
            try process.run()
            guideProcess = process
        } catch {
            showError("La guida di Kreluna Agent non è riuscita ad aprirsi.")
        }
    }

    private func showError(_ message: String) {
        let alert = NSAlert()
        alert.messageText = "Kreluna Agent"
        alert.informativeText = message
        alert.runModal()
    }
}

if CommandLine.arguments.contains("--capture-frame") {
    Task {
        let result: [String: Any]
        if #available(macOS 14.0, *) {
            do { result = try await captureNativeFrame() }
            catch { result = ["error": "Cattura nativa non disponibile: verifica il permesso Registrazione schermo di Kreluna Agent."] }
        } else {
            result = ["error": "La visualizzazione remota richiede macOS 14 o successivo"]
        }
        if let data = try? JSONSerialization.data(withJSONObject: result) {
            FileHandle.standardOutput.write(data)
        }
        exit(0)
    }
    RunLoop.main.run()
    exit(1)
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
