import AppKit
import Foundation
import UniformTypeIdentifiers
import WebKit

private let allowedHosts = Set(["127.0.0.1", "localhost", "::1"])

private func isDirectorURL(_ url: URL?) -> Bool {
    guard let url,
          url.scheme == "http",
          let host = url.host?.lowercased(),
          allowedHosts.contains(host),
          url.port == 8080 else {
        return false
    }
    return url.user == nil && url.password == nil
}

final class KrelunaDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate, WKDownloadDelegate {
    private let startURL: URL
    private var window: NSWindow?
    private var webView: WKWebView?
    private var activeDownloads: [WKDownload] = []

    init(startURL: URL) {
        self.startURL = startURL
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMenus()

        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .default()
        let view = WKWebView(frame: .zero, configuration: configuration)
        view.navigationDelegate = self
        view.uiDelegate = self
        view.underPageBackgroundColor = NSColor(
            calibratedRed: 7.0 / 255.0,
            green: 16.0 / 255.0,
            blue: 31.0 / 255.0,
            alpha: 1.0
        )

        let frame = NSRect(x: 0, y: 0, width: 1440, height: 900)
        let appWindow = NSWindow(
            contentRect: frame,
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        appWindow.title = "Kreluna Director"
        appWindow.minSize = NSSize(width: 1100, height: 700)
        appWindow.backgroundColor = NSColor(
            calibratedRed: 7.0 / 255.0,
            green: 16.0 / 255.0,
            blue: 31.0 / 255.0,
            alpha: 1.0
        )
        appWindow.contentView = view
        appWindow.center()
        appWindow.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)

        window = appWindow
        webView = view
        view.load(URLRequest(url: startURL))
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        if navigationAction.shouldPerformDownload {
            decisionHandler(.download)
            return
        }
        guard let url = navigationAction.request.url else {
            decisionHandler(.cancel)
            return
        }
        if isDirectorURL(url) {
            decisionHandler(.allow)
            return
        }
        if ["https", "http"].contains(url.scheme?.lowercased() ?? "") {
            NSWorkspace.shared.open(url)
        }
        decisionHandler(.cancel)
    }

    func webView(
        _ webView: WKWebView,
        navigationAction: WKNavigationAction,
        didBecome download: WKDownload
    ) {
        track(download)
    }

    func webView(
        _ webView: WKWebView,
        navigationResponse: WKNavigationResponse,
        didBecome download: WKDownload
    ) {
        track(download)
    }

    private func track(_ download: WKDownload) {
        activeDownloads.append(download)
        download.delegate = self
    }

    func download(
        _ download: WKDownload,
        decideDestinationUsing response: URLResponse,
        suggestedFilename: String,
        completionHandler: @escaping (URL?) -> Void
    ) {
        guard let downloads = FileManager.default.urls(
            for: .downloadsDirectory,
            in: .userDomainMask
        ).first else {
            completionHandler(nil)
            return
        }
        let requested = URL(fileURLWithPath: suggestedFilename).lastPathComponent
        let fallback = "kreluna-fort-knox-modello.csv"
        let name = requested.isEmpty ? fallback : requested
        let source = URL(fileURLWithPath: name)
        let stem = source.deletingPathExtension().lastPathComponent
        let suffix = source.pathExtension
        var destination = downloads.appendingPathComponent(name)
        var copy = 2
        while FileManager.default.fileExists(atPath: destination.path) {
            let candidate = suffix.isEmpty ? "\(stem)-\(copy)" : "\(stem)-\(copy).\(suffix)"
            destination = downloads.appendingPathComponent(candidate)
            copy += 1
        }
        completionHandler(destination)
    }

    func downloadDidFinish(_ download: WKDownload) {
        activeDownloads.removeAll { $0 === download }
    }

    func download(
        _ download: WKDownload,
        didFailWithError error: Error,
        resumeData: Data?
    ) {
        activeDownloads.removeAll { $0 === download }
        let alert = NSAlert()
        alert.messageText = "Download non riuscito"
        alert.informativeText = error.localizedDescription
        alert.runModal()
    }

    func webView(
        _ webView: WKWebView,
        createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction,
        windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        if let url = navigationAction.request.url,
           !isDirectorURL(url),
           ["https", "http"].contains(url.scheme?.lowercased() ?? "") {
            NSWorkspace.shared.open(url)
        }
        return nil
    }

    func webView(
        _ webView: WKWebView,
        runOpenPanelWith parameters: WKOpenPanelParameters,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping ([URL]?) -> Void
    ) {
        let panel = NSOpenPanel()
        panel.title = "Importa accessi in Fort Knox"
        panel.prompt = "Importa CSV"
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        panel.allowedContentTypes = [UTType.commaSeparatedText]
        guard let window else {
            completionHandler(panel.runModal() == .OK ? panel.urls : nil)
            return
        }
        panel.beginSheetModal(for: window) { response in
            completionHandler(response == .OK ? panel.urls : nil)
        }
    }

    private func installMenus() {
        let menuBar = NSMenu()

        let appItem = NSMenuItem()
        menuBar.addItem(appItem)
        let appMenu = NSMenu(title: "Kreluna Director")
        appMenu.addItem(
            withTitle: "Chiudi Kreluna Director",
            action: #selector(NSApplication.terminate(_:)),
            keyEquivalent: "q"
        )
        appItem.submenu = appMenu

        let editItem = NSMenuItem()
        menuBar.addItem(editItem)
        let editMenu = NSMenu(title: "Modifica")
        editMenu.addItem(withTitle: "Annulla", action: Selector(("undo:")), keyEquivalent: "z")
        editMenu.addItem(withTitle: "Ripristina", action: Selector(("redo:")), keyEquivalent: "Z")
        editMenu.addItem(NSMenuItem.separator())
        editMenu.addItem(withTitle: "Taglia", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        editMenu.addItem(withTitle: "Copia", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        editMenu.addItem(withTitle: "Incolla", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        editMenu.addItem(
            withTitle: "Seleziona tutto",
            action: #selector(NSText.selectAll(_:)),
            keyEquivalent: "a"
        )
        editItem.submenu = editMenu

        NSApp.mainMenu = menuBar
    }
}

guard CommandLine.arguments.count == 2,
      let startURL = URL(string: CommandLine.arguments[1]),
      isDirectorURL(startURL) else {
    fputs("Indirizzo Director locale non valido\n", stderr)
    exit(2)
}

let application = NSApplication.shared
application.setActivationPolicy(.regular)
let delegate = KrelunaDelegate(startURL: startURL)
application.delegate = delegate
application.run()
