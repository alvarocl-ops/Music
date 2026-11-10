//
//  KaraokeSeparationService.swift
//  Trop
//
//  Created on 10/11/2026.
//

import Foundation
import SwiftUI
import Combine

public struct StemsResponse: Codable {
    public let status: String // "ready", "processing", "error", "not_found"
    public let progress: Double?
    public let message: String?
    public let quadUrl: String?
    public let instrumentalUrl: String?
    public let vocalsUrl: String?

    enum CodingKeys: String, CodingKey {
        case status
        case progress
        case message
        case quadUrl = "quad_url"
        case instrumentalUrl = "instrumental_url"
        case vocalsUrl = "vocals_url"
    }
}

public struct StemsInfo: Equatable {
    public let videoId: String
    public let quadURL: URL
    public let instrumentalURL: URL?
    public let vocalsURL: URL?
}

@MainActor
public final class KaraokeSeparationService: ObservableObject {
    public static let shared = KaraokeSeparationService()

    public enum State: Equatable {
        case idle
        case requesting
        case processing(progress: Double)
        case ready(stems: StemsInfo)
        case failed(error: String)
    }

    @Published public private(set) var state: State = .idle
    @Published public private(set) var activeStemsForCurrentTrack: StemsInfo?

    private var pollingTask: Task<Void, Never>?
    private var currentVideoId: String?
    private var memoryCache: [String: StemsInfo] = [:]

    private init() {}

    public func handleTrackChanged(videoId: String?) {
        currentVideoId = videoId
        pollingTask?.cancel()
        pollingTask = nil

        guard let videoId, !videoId.isEmpty else {
            state = .idle
            activeStemsForCurrentTrack = nil
            return
        }

        if let cached = memoryCache[videoId] {
            state = .ready(stems: cached)
            activeStemsForCurrentTrack = cached
            applyQuadStemsIfKaraokeActive(cached)
        } else {
            state = .idle
            activeStemsForCurrentTrack = nil
            let serverURL = SettingsStore.shared.karaokeServerURL.trimmingCharacters(in: .whitespacesAndNewlines)
            if SettingsStore.shared.karaokeModeEnabled && !serverURL.isEmpty && SettingsStore.shared.karaokeUseAI {
                requestSeparation(videoId: videoId)
            }
        }
    }

    public func requestSeparation(videoId: String) {
        let rawServerURL = SettingsStore.shared.karaokeServerURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let baseURL = URL(string: rawServerURL), !rawServerURL.isEmpty else {
            state = .failed(error: "Servidor no configurado")
            return
        }

        pollingTask?.cancel()
        state = .requesting

        pollingTask = Task { [weak self] in
            guard let self else { return }
            do {
                // 1. Trigger POST /api/separate
                var request = URLRequest(url: baseURL.appendingPathComponent("api/separate"))
                request.httpMethod = "POST"
                request.setValue("application/json", forHTTPHeaderField: "Content-Type")
                let body: [String: Any] = [
                    "video_id": videoId,
                    "title": NowPlaying.shared.title,
                    "artist": NowPlaying.shared.artist
                ]
                request.httpBody = try JSONSerialization.data(withJSONObject: body)
                request.timeoutInterval = 10

                _ = try? await URLSession.shared.data(for: request)

                // 2. Poll GET /api/stems/<videoId>
                let pollURL = baseURL.appendingPathComponent("api/stems/\(videoId)")
                var attempts = 0
                while !Task.isCancelled && attempts < 120 {
                    attempts += 1
                    try await Task.sleep(nanoseconds: 2_000_000_000)

                    guard let (data, response) = try? await URLSession.shared.data(from: pollURL),
                          let httpResp = response as? HTTPURLResponse,
                          (200...299).contains(httpResp.statusCode) else {
                        continue
                    }

                    if let decoded = try? JSONDecoder().decode(StemsResponse.self, from: data) {
                        if decoded.status == "ready", let quadStr = decoded.quadUrl, let quad = URL(string: quadStr, relativeTo: baseURL) {
                            let instURL = decoded.instrumentalUrl.flatMap { URL(string: $0, relativeTo: baseURL) }
                            let vocURL = decoded.vocalsUrl.flatMap { URL(string: $0, relativeTo: baseURL) }
                            let info = StemsInfo(videoId: videoId, quadURL: quad.absoluteURL, instrumentalURL: instURL?.absoluteURL, vocalsURL: vocURL?.absoluteURL)
                            self.memoryCache[videoId] = info
                            self.state = .ready(stems: info)
                            self.activeStemsForCurrentTrack = info
                            self.applyQuadStemsIfKaraokeActive(info)
                            break
                        } else if decoded.status == "processing" {
                            let prog = decoded.progress ?? 0.0
                            self.state = .processing(progress: prog)
                        } else if decoded.status == "error" {
                            self.state = .failed(error: decoded.message ?? "Error en el servidor")
                            break
                        }
                    }
                }
            } catch {
                if !Task.isCancelled {
                    self.state = .failed(error: error.localizedDescription)
                }
            }
        }
    }

    public func applyQuadStemsIfKaraokeActive(_ stems: StemsInfo) {
        guard SettingsStore.shared.karaokeModeEnabled,
              SettingsStore.shared.karaokeUseAI,
              NowPlaying.shared.videoId == stems.videoId else { return }
        PlayerController.shared.switchToQuadStems(url: stems.quadURL)
    }

    public func cancel() {
        pollingTask?.cancel()
        pollingTask = nil
        state = .idle
    }
}
