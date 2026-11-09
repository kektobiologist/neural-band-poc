// Native login helper. Account tokens travel over stdout only to the parent
// enrollment process; the parent must never log this output.
import AppKit
import WebKit
import Foundation

@main
@MainActor
final class Login: NSObject, NSApplicationDelegate, NSWindowDelegate, WKNavigationDelegate, WKUIDelegate {
    var window: NSWindow!
    var web: WKWebView!
    var tokens: MetaAuth.SSOTokens?
    var exchanging = false
    var popups: [NSWindow] = []

    func status(_ message: String) {
        FileHandle.standardError.write(Data(("[meta-login] " + message + "\n").utf8))
    }

    static func main() {
        if CommandLine.arguments.contains("--self-test") {
            for scheme in ["oculus", "fb-viewapp"] {
                precondition(MetaAuth.isLoginCallback(URL(string: scheme + "://frl_login?token=test&blob=test")!))
                precondition(!MetaAuth.isLoginCallback(URL(string: scheme + "://other/frl_login")!))
            }
            precondition(!MetaAuth.isLoginCallback(URL(string: "https://example.com/frl_login")!))
            precondition(!MetaAuth.isLoginCallback(URL(string: "oculus://frl_login/unexpected")!))
            precondition(MetaAuth.callbackMatches(MetaAuth.expectedCallbackToken(nativeSSOToken: "test"), nativeSSOToken: "test"))
            precondition(!MetaAuth.callbackMatches("0000000000000000", nativeSSOToken: "test"))
            print("Login callback checks passed")
            exit(0)
        }
        let store = MetaSessionStore()
        if CommandLine.arguments.contains("--forget") {
            store.deleteSession()
            exit(0)
        }
        if !CommandLine.arguments.contains("--login"), let session = store.restoreSession() {
            output(session)
        }
        let app = NSApplication.shared
        let delegate = Login()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        withExtendedLifetime(delegate) { app.run() }
    }

    static func output(_ session: MetaSession) -> Never {
        let data = try! JSONSerialization.data(withJSONObject: [
            "access_token": session.accessToken, "user_id": session.userID,
            "device_id": session.deviceID, "universe": MetaSession.universe])
        FileHandle.standardOutput.write(data)
        exit(0)
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        status("opening sign-in")
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 720, height: 760),
                          styleMask: [.titled, .closable, .resizable], backing: .buffered, defer: false)
        window.title = "Neural Band — sign in with Meta"
        window.delegate = self
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        web = WKWebView(frame: window.contentView!.bounds, configuration: config)
        web.autoresizingMask = [.width, .height]
        web.navigationDelegate = self
        web.uiDelegate = self
        window.contentView!.addSubview(web)
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        Task {
            do {
                let value = try await MetaAuth.tokensQuery()
                tokens = value
                status("sign-in tokens received")
                guard let url = value.authEntryURL else { fail("Invalid Meta sign-in URL.") }
                web.load(URLRequest(url: url))
            } catch { fail(error.localizedDescription) }
        }
    }

    func windowWillClose(_ notification: Notification) { exit(2) }

    func fail(_ message: String) -> Never {
        status(message)
        exit(1)
    }

    func webView(_ webView: WKWebView, didCommit navigation: WKNavigation!) {
        window.title = "Neural Band — " + (webView.url?.host ?? "Meta sign-in")
        status("page loaded: " + (webView.url?.host ?? "unknown host"))
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
        if (error as NSError).code != NSURLErrorCancelled { fail("Could not load Meta sign-in. Check your connection and retry.") }
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = action.request.url else { decisionHandler(.cancel); return }
        status("navigation: " + (url.scheme ?? "none") + " " + (url.host ?? "no host"))
        if MetaAuth.isLoginCallback(url) {
            decisionHandler(.cancel)
            guard !exchanging, let tokens else { return }
            let items = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
            let matches = items.filter { $0.name == "token" }
            let blobs = items.filter { $0.name == "blob" }
            guard matches.count == 1, blobs.count == 1, let blob = blobs[0].value, !blob.isEmpty,
                  MetaAuth.callbackMatches(matches[0].value, nativeSSOToken: tokens.nativeSSOToken) else {
                fail("Meta returned a callback for a different login. Retry sign-in.")
            }
            exchanging = true
            status("validated login callback")
            window.title = "Neural Band — completing Meta sign-in"
            Task {
                do {
                    let frl = try await MetaAuth.decryptBlob(blob, requestToken: tokens.nativeSSOToken)
                    let session = try await MetaAuth.login(frlAccessToken: frl)
                    status("Meta session received")
                    MetaSessionStore().saveSession(session)
                    Self.output(session)
                } catch { fail(error.localizedDescription) }
            }
        } else {
            if url.scheme != "https" && url.absoluteString != "about:blank" {
                status("blocked unsupported navigation scheme")
            }
            decisionHandler(url.scheme == "https" || url.absoluteString == "about:blank" ? .allow : .cancel)
        }
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        // Returning nil breaks window.open() flows which navigate the returned
        // window later. Preserve the supplied configuration and its shared session.
        let child = WKWebView(frame: NSRect(x: 0, y: 0, width: 720, height: 760), configuration: configuration)
        child.navigationDelegate = self
        child.uiDelegate = self
        let popup = NSWindow(contentRect: child.frame, styleMask: [.titled, .closable, .resizable],
                             backing: .buffered, defer: false)
        popup.title = "Neural Band — Meta sign-in"
        popup.contentView = child
        popup.isReleasedWhenClosed = false
        popups.append(popup)
        popup.center()
        popup.makeKeyAndOrderFront(nil)
        status("opened login popup")
        return child
    }

    func webViewDidClose(_ webView: WKWebView) {
        if let popup = popups.first(where: { $0.contentView === webView }) {
            popup.close()
            popups.removeAll { $0 === popup }
        }
    }
}
