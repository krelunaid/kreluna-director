import AppKit
import Foundation
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

final class KrelunaDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate {
    private let startURL: URL
    private var window: NSWindow?
    private var webView: WKWebView?

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
