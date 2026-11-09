//
//  LoginWebView.swift
//  Trop
//
//  Created by 686udjie on 28/06/2026.
//

@preconcurrency import SwiftUI
import SwiftyTube
import WebKit

// Presented as a sheet — launches Google OAuth in a full-screen WKWebView
struct LoginWebView: View {
    let model: LoginViewModel

    var body: some View {
        Presenter(model: model)
            .ignoresSafeArea()
    }
}

// Bridges the WKWebView into SwiftUI using a hosting controller
private struct Presenter: UIViewControllerRepresentable {
    typealias UIViewControllerType = WebLoginController

    let model: LoginViewModel

    func makeUIViewController(context: UIViewControllerRepresentableContext<Presenter>) -> WebLoginController {
        WebLoginController(model: model)
    }

    func updateUIViewController(_ vc: WebLoginController, context: UIViewControllerRepresentableContext<Presenter>) {}

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    class Coordinator {}
}

// Controller that hosts a WKWebView for the Google OAuth flow
final class WebLoginController: UIViewController {
    let model: LoginViewModel
    private var delegate: LoginNavigationDelegate?

    init(model: LoginViewModel) {
        self.model = model
        super.init(nibName: nil, bundle: nil)
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override func viewDidLoad() {
        super.viewDidLoad()

        let delegate = LoginNavigationDelegate(model: model)
        self.delegate = delegate

        let config = WKWebViewConfiguration()
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.customUserAgent = LoginWebviewHarvest.userAgent
        webView.navigationDelegate = delegate
        view = webView

        let url = URL(string: "https://accounts.google.com/ServiceLogin?service=youtube&continue=https://music.youtube.com")!
        webView.load(URLRequest(url: url))
    }
}

// Handles navigation and extracts auth cookies on login redirect
private final class LoginNavigationDelegate: NSObject, WKNavigationDelegate {
    let model: LoginViewModel
    private var didCaptureSession = false

    init(model: LoginViewModel) {
        self.model = model
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        guard let url = webView.url, url.host?.contains("music.youtube.com") == true else {
            return
        }
        guard !didCaptureSession, !model.isLoggedIn else { return }

        Log.login.debug("Redirected to \(url.host ?? "") — collecting cookies...")

        let dismissPromo = """
        (function() {
          var style = document.createElement('style');
          style.textContent = 'ytmusic-app-promo-renderer,#smart-banner,.smart-banner,\\
            [aria-label*="YouTube Music app"],tp-yt-paper-dialog[aria-label*="app"]{display:none!important}';
          document.head.appendChild(style);
          var dismiss = function() {
            var clickable = document.querySelectorAll('button,tp-yt-paper-button,yt-button-shape button,button[role="button"]');
            for (var i = 0; i < clickable.length; i++) {
              var t = (clickable[i].textContent || '').trim().toLowerCase();
              if (t === 'not now' || t === 'skip') { clickable[i].click(); break; }
            }
          };
          dismiss();
          setTimeout(dismiss, 1200);
        })();
        """
        webView.evaluateJavaScript(dismissPromo, completionHandler: nil)

        startHarvest(webView: webView)
    }

    private func startHarvest(webView: WKWebView) {
        Task { @MainActor [weak self, weak webView] in
            guard let webView else { return }
            let session = await LoginWebviewHarvest.collectSession(from: webView) { [weak self] in
                guard let self, !self.didCaptureSession, !self.model.isLoggedIn else { return false }
                return true
            }
            guard let self, let (harvested, sapisid) = session else { return }
            self.importSession(harvested: harvested, sapisid: sapisid, webView: webView)
        }
    }
    private func importSession(harvested: [String: String], sapisid: String, webView: WKWebView) {
        didCaptureSession = true
        model.handleLogin(
            cookies: harvested,
            sapisid: sapisid,
            visitorData: harvested["visitor_data"],
            dataSyncId: model.dataSyncId
        )

        // Extract dataSyncId from the YouTube page config via JS injection
        webView.evaluateJavaScript("window.yt?.config_?.DATASYNC_ID ?? ''") { [weak self] result, error in
            if let dataSyncId = result as? String, !dataSyncId.isEmpty {
                self?.model.dataSyncId = dataSyncId
                Log.login.debug("  ✅ Found dataSyncId: \(dataSyncId.prefix(15))...")
            } else if let error {
                Log.login.error("  ⚠️ JS eval for dataSyncId failed: \(error.localizedDescription)")
            } else {
                Log.login.debug("  ⚠️ dataSyncId not found in page context")
            }
        }
    }
}
