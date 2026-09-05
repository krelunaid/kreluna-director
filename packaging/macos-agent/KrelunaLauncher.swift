import Cocoa
import Darwin
import ScreenCaptureKit

// Invoked only by the authenticated remote-session worker. No listening port
// on the network, files, or frame logging: frames stay on a local UNIX socket
// owned by the LaunchServices-launched app process (same TCC identity).
func ensureScreenCaptureAccess() -> Bool {
    // TCC prompts must run on the main thread; background socket workers otherwise
    // get a silent denial even when Settings appears enabled.
    if Thread.isMainThread {
        return CGPreflightScreenCaptureAccess() || CGRequestScreenCaptureAccess()
    }
    var allowed = false
    DispatchQueue.main.sync {
        allowed = CGPreflightScreenCaptureAccess() || CGRequestScreenCaptureAccess()
    }
    return allowed
}

func openScreenCaptureSettings() {
    let urls = [
        "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
        "x-apple.systempreferences:com.apple.Settings.PrivacySecurity.extension?Privacy_ScreenCapture",
    ]
    for raw in urls {
        if let url = URL(string: raw), NSWorkspace.shared.open(url) { return }
    }
}

@available(macOS 14.0, *)
func captureNativeFrame() async throws -> [String: Any] {
    guard ensureScreenCaptureAccess() else {
        openScreenCaptureSettings()
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

func encodeCapturePayload(_ result: [String: Any]) -> Data {
    (try? JSONSerialization.data(withJSONObject: result)) ?? Data("{\"error\":\"JSON non disponibile\"}".utf8)
}

/// Local capture bridge. Spawning `Kreluna --capture-frame` as a CLI child loses
/// the LaunchServices TCC identity after re-signing; keep ScreenCaptureKit in
/// the same process that was opened as Kreluna Agent.app.
final class CaptureSocketServer {
    private let path: String
    private var listenFD: Int32 = -1
    private let queue = DispatchQueue(label: "studio.kreluna.agent.capture")

    init(path: String) {
        self.path = path
    }

    func start() {
        unlink(path)
        listenFD = socket(AF_UNIX, SOCK_STREAM, 0)
        guard listenFD >= 0 else { return }

        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        let maxPath = MemoryLayout.size(ofValue: addr.sun_path)
        let pathBytes = Array(path.utf8)
        guard pathBytes.count + 1 <= maxPath else {
            close(listenFD)
            listenFD = -1
            return
        }
        withUnsafeMutablePointer(to: &addr.sun_path) { ptr in
            ptr.withMemoryRebound(to: UInt8.self, capacity: maxPath) { bytes in
                for i in 0..<pathBytes.count {
                    bytes[i] = pathBytes[i]
                }
                bytes[pathBytes.count] = 0
            }
        }

        let bindSize = socklen_t(MemoryLayout<sockaddr_un>.size)
        let bindResult = withUnsafePointer(to: &addr) { ptr in
            ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockPtr in
                Darwin.bind(listenFD, sockPtr, bindSize)
            }
        }
        guard bindResult == 0, Darwin.listen(listenFD, 2) == 0 else {
            close(listenFD)
            listenFD = -1
            return
        }
        chmod(path, 0o600)

        queue.async { [weak self] in
            self?.acceptLoop()
        }
    }

    func stop() {
        if listenFD >= 0 {
            close(listenFD)
            listenFD = -1
        }
        unlink(path)
    }

    private func acceptLoop() {
        while listenFD >= 0 {
            let client = Darwin.accept(listenFD, nil, nil)
            if client < 0 {
                if errno == EINTR { continue }
                break
            }
            handleClient(client)
        }
    }

    private func handleClient(_ client: Int32) {
        defer { close(client) }
        var buffer = Data()
        var chunk = [UInt8](repeating: 0, count: 4096)
        while true {
            let n = read(client, &chunk, chunk.count)
            if n < 0 {
                if errno == EINTR { continue }
                return
            }
            if n == 0 { return }
            buffer.append(contentsOf: chunk[0..<n])
            if buffer.contains(UInt8(ascii: "\n")) { break }
            if buffer.count > 64_000 { return }
        }

        let semaphore = DispatchSemaphore(value: 0)
        var payload = Data("{\"error\":\"Cattura non riuscita\"}".utf8)
        if #available(macOS 14.0, *) {
            Task {
                let result: [String: Any]
                do { result = try await captureNativeFrame() }
                catch { result = ["error": "Cattura nativa non disponibile: verifica il permesso Registrazione schermo di Kreluna Agent."] }
                payload = encodeCapturePayload(result)
                semaphore.signal()
            }
        } else {
            payload = encodeCapturePayload(["error": "La visualizzazione remota richiede macOS 14 o successivo"])
            semaphore.signal()
        }
        _ = semaphore.wait(timeout: .now() + 12)
        var toWrite = payload
        toWrite.append(UInt8(ascii: "\n"))
        _ = toWrite.withUnsafeBytes { raw in
            guard let base = raw.bindMemory(to: UInt8.self).baseAddress else { return 0 }
            return write(client, base, toWrite.count)
        }
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    private var agentProcess: Process?
    private var guideProcess: Process?
    private var captureServer: CaptureSocketServer?
    private var captureSocketPath: String?

    func applicationDidFinishLaunching(_ notification: Notification) {
        requestScreenPermissionIfNeeded()
        startCaptureServer()
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
        captureServer?.stop()
    }

    private func requestScreenPermissionIfNeeded() {
        // Ask from the LS-launched app itself so System Settings binds the grant
        // to studio.kreluna.agent / current code signature — not to a CLI child.
        if ensureScreenCaptureAccess() { return }
        openScreenCaptureSettings()
    }

    private func startCaptureServer() {
        guard
            let support = FileManager.default.urls(
                for: .applicationSupportDirectory,
                in: .userDomainMask
            ).first
        else { return }
        let dataRoot = support.appendingPathComponent("KrelunaAgent")
        try? FileManager.default.createDirectory(
            at: dataRoot.appendingPathComponent("data"),
            withIntermediateDirectories: true
        )
        let sockURL = dataRoot.appendingPathComponent("capture.sock")
        captureSocketPath = sockURL.path
        let server = CaptureSocketServer(path: sockURL.path)
        server.start()
        captureServer = server
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
        // Prefer the in-app socket. Keep the executable path only as a legacy
        // fallback; CLI --capture-frame does not inherit TCC after re-sign.
        if let sock = captureSocketPath {
            environment["KRELUNA_NATIVE_CAPTURE_SOCK"] = sock
        }
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
    // Legacy CLI entry. Prefer the UNIX socket owned by the LS-launched app.
    Task {
        let result: [String: Any]
        if #available(macOS 14.0, *) {
            do { result = try await captureNativeFrame() }
            catch { result = ["error": "Cattura nativa non disponibile: verifica il permesso Registrazione schermo di Kreluna Agent."] }
        } else {
            result = ["error": "La visualizzazione remota richiede macOS 14 o successivo"]
        }
        FileHandle.standardOutput.write(encodeCapturePayload(result))
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
