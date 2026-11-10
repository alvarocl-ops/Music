//
//  KaraokeSettingsView.swift
//  Trop
//
//  Created on 10/11/2026.
//

import SwiftUI

struct KaraokeSettingsView: View {
    @Environment(\.settingsStore) private var settings
    @State private var isTesting = false
    @State private var testResult: String?
    @State private var isSuccess: Bool = false

    var body: some View {
        @Bindable var settings = settings

        List {
            Section {
                VStack(alignment: .leading, spacing: 10) {
                    HStack(spacing: 12) {
                        Image(systemName: "mic.badge.sparkle")
                            .font(.system(size: 32))
                            .foregroundStyle(.tint)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Karaoke con IA (Demucs)")
                                .font(.headline)
                            Text("Separación de pistas vocales e instrumentales de calidad de estudio.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                .padding(.vertical, 4)
            }

            Section {
                SettingsToggleRow(
                    "Activar separación por IA",
                    icon: "sparkles",
                    isOn: $settings.karaokeUseAI
                )

                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Image(systemName: "server.rack")
                            .foregroundStyle(.secondary)
                        Text("URL del servidor")
                            .font(.subheadline)
                    }
                    TextField("https://tu-space.hf.space o http://ip:8000", text: $settings.karaokeServerURL)
                        .textFieldStyle(.roundedBorder)
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                }
                .padding(.vertical, 4)

                Button {
                    Task { await testConnection() }
                } label: {
                    HStack {
                        if isTesting {
                            ProgressView()
                                .padding(.trailing, 6)
                        } else {
                            Image(systemName: "antenna.radiowaves.left.and.right")
                        }
                        Text("Probar conexión con el servidor")
                        Spacer()
                    }
                }
                .disabled(settings.karaokeServerURL.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isTesting)

                if let testResult {
                    HStack(spacing: 8) {
                        Image(systemName: isSuccess ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                            .foregroundStyle(isSuccess ? .green : .red)
                        Text(testResult)
                            .font(.caption)
                            .foregroundStyle(isSuccess ? .green : .red)
                    }
                }
            } header: {
                Text("Servidor de IA")
            } footer: {
                Text("Puedes desplegar tu propio servidor en Hugging Face Spaces (100% gratuito con GPU) o en tu PC local usando Docker con los archivos incluidos en la carpeta server/ del proyecto.")
            }

            Section {
                VStack(alignment: .leading, spacing: 8) {
                    Label("Calidad de estudio sin eco", systemImage: "waveform.badge.magnifyingglass")
                        .font(.subheadline.weight(.semibold))
                    Text("A diferencia de los filtros clásicos que restan canales y dejan un residuo de eco de la reverberación, el modelo de IA Demucs aísla limpiamente la voz de la pista instrumental completa (con bajo, batería y guitarras intactos).")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(.vertical, 4)

                VStack(alignment: .leading, spacing: 8) {
                    Label("Filtro DSP como respaldo", systemImage: "slider.vertical.3")
                        .font(.subheadline.weight(.semibold))
                    Text("Si el servidor no está disponible o mientras se procesa la pista, Trop utiliza un filtro DSP en fase en tiempo real para atenuar la voz central de forma instantánea.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(.vertical, 4)
            } header: {
                Text("¿Cómo funciona?")
            }
        }
        .navigationTitle("Karaoke IA")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func testConnection() async {
        let raw = settings.karaokeServerURL.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: raw) else {
            testResult = "URL inválida"
            isSuccess = false
            return
        }

        isTesting = true
        testResult = nil

        let healthURL = url.appendingPathComponent("api/health")
        var request = URLRequest(url: healthURL)
        request.timeoutInterval = 8

        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            if let http = response as? HTTPURLResponse, (200...299).contains(http.statusCode) {
                if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                   let device = json["device"] as? String {
                    testResult = "Conexión exitosa. Dispositivo: \(device.uppercased())"
                } else {
                    testResult = "Conexión exitosa con el servidor."
                }
                isSuccess = true
            } else {
                testResult = "Error HTTP \((response as? HTTPURLResponse)?.statusCode ?? -1)"
                isSuccess = false
            }
        } catch {
            testResult = "No se pudo conectar: \(error.localizedDescription)"
            isSuccess = false
        }
        isTesting = false
    }
}
