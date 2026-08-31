import SwiftUI
import UIKit
import PPLCoachCore

/// Fotos nach der Session -- Slot für Slot, mit vorgegebener Pose.
///
/// Konstanz ist das, was Fotos überhaupt vergleichbar macht: gleicher Ort,
/// gleiches Licht, gleiche Pose, und beim Auslösen das Vorgängerfoto als
/// halbtransparente Schablone.
struct PhotoStepView: View {
    @EnvironmentObject private var store: Store
    let day: TrainingDay
    let slots: [PhotoSlot]
    let onFinish: (SessionTag) -> Void

    @State private var index = 0
    @State private var showCamera = false
    @State private var showTagQuestion = false

    private var currentSlot: PhotoSlot? {
        index < slots.count ? slots[index] : nil
    }

    var body: some View {
        VStack(spacing: 0) {
            if let slot = currentSlot {
                slotScreen(slot)
            } else {
                finishScreen
            }
        }
        .sheet(isPresented: $showCamera) {
            if let slot = currentSlot {
                CameraView(
                    ghostImage: ghostImage(for: slot),
                    instruction: slot.poseInstruction
                ) { image in
                    save(image, slot: slot)
                    advance()
                }
                .ignoresSafeArea()
            }
        }
    }

    private func slotScreen(_ slot: PhotoSlot) -> some View {
        VStack(spacing: 0) {
            VStack(spacing: 6) {
                Text("FOTO \(index + 1) VON \(slots.count)")
                    .font(.system(size: 12, weight: .semibold))
                    .tracking(1.4)
                    .foregroundStyle(GymTheme.secondaryText)
                Text(slot.displayName)
                    .font(.system(size: 30, weight: .bold))
                    .foregroundStyle(GymTheme.primaryText)
                    .multilineTextAlignment(.center)
            }
            .padding(.top, 30)

            Spacer()

            VStack(alignment: .leading, spacing: 16) {
                Text(slot.poseInstruction)
                    .font(.system(size: 17))
                    .foregroundStyle(GymTheme.primaryText)

                Divider().overlay(GymTheme.stroke)

                ForEach(PhotoProtocolHint.all, id: \.self) { hint in
                    HStack(alignment: .top, spacing: 10) {
                        Image(systemName: "circle.fill")
                            .font(.system(size: 5))
                            .padding(.top, 7)
                        Text(hint)
                    }
                    .font(.system(size: 14))
                    .foregroundStyle(GymTheme.secondaryText)
                }

                if let previous = store.lastPhoto(slot: slot) {
                    if let note = previous.locationNote {
                        Text("Ort beim letzten Mal: \(note)")
                            .font(.system(size: 14, weight: .medium))
                            .foregroundStyle(GymTheme.Mode.rest.accent)
                    }
                } else {
                    Text("Erstes Foto in diesem Slot -- notiere danach in den Einstellungen, wo du standest.")
                        .font(.system(size: 13))
                        .foregroundStyle(GymTheme.secondaryText)
                }
            }
            .padding(20)
            .background(GymTheme.surface, in: RoundedRectangle(cornerRadius: 18))
            .padding(.horizontal, 20)

            Spacer()

            VStack(spacing: 12) {
                PrimaryButton(
                    title: UIImagePickerController.isSourceTypeAvailable(.camera)
                        ? "Kamera öffnen"
                        : "Foto wählen",
                    mode: .entry
                ) {
                    showCamera = true
                }
                SecondaryButton(title: "Diesen Slot überspringen") { advance() }
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 24)
        }
    }

    private var finishScreen: some View {
        VStack(spacing: 26) {
            Spacer()
            Text("Wie war die Session?")
                .font(.system(size: 26, weight: .bold))
                .foregroundStyle(GymTheme.primaryText)
            Text("Ein Tap. Wird gebraucht, damit ein mieser Tag später nicht als Stagnation zählt.")
                .font(.system(size: 15))
                .foregroundStyle(GymTheme.secondaryText)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 30)

            VStack(spacing: 12) {
                ForEach(SessionTag.allCases, id: \.self) { tag in
                    Button {
                        Haptics.tap()
                        onFinish(tag)
                    } label: {
                        Text(tag.displayName)
                            .font(.system(size: 20, weight: .semibold))
                            .foregroundStyle(GymTheme.primaryText)
                            .frame(maxWidth: .infinity)
                            .frame(height: 70)
                            .background(GymTheme.surface, in: RoundedRectangle(cornerRadius: 16))
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 24)

            Spacer()
        }
    }

    private func advance() {
        index += 1
    }

    private func ghostImage(for slot: PhotoSlot) -> UIImage? {
        guard let previous = store.lastPhoto(slot: slot) else { return nil }
        return UIImage(contentsOfFile: store.photoURL(for: previous).path)
    }

    private func save(_ image: UIImage, slot: PhotoSlot) {
        let previous = store.lastPhoto(slot: slot)
        let fileName = "\(slot.rawValue)-\(Int(Date().timeIntervalSince1970)).jpg"
        let record = PhotoRecord(
            sessionID: nil,
            slot: slot,
            takenAt: Date(),
            fileName: fileName,
            locationNote: previous?.locationNote,
            previousPhotoID: previous?.id,
            bodyweightAtTime: store.latestBodyweight
        )
        if let data = image.jpegData(compressionQuality: 0.9) {
            try? data.write(to: store.photoURL(for: record), options: .atomic)
        }
        store.add(record)
    }
}

/// Kamera mit Schablone: das Vorgängerfoto liegt halbtransparent über dem
/// Livebild. Das ist der wirksamste einzelne Trick für vergleichbare
/// Verlaufsfotos -- und kostet nichts.
struct CameraView: UIViewControllerRepresentable {
    let ghostImage: UIImage?
    let instruction: String
    let onCapture: (UIImage) -> Void

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.delegate = context.coordinator
        if UIImagePickerController.isSourceTypeAvailable(.camera) {
            picker.sourceType = .camera
            picker.cameraDevice = .rear
            // Schablone nur auf der echten Kamera -- im Simulator fällt die
            // App auf die Mediathek zurück, und dort gibt es kein Overlay.
            picker.cameraOverlayView = makeOverlay(size: UIScreen.main.bounds.size)
        } else {
            picker.sourceType = .photoLibrary
        }
        return picker
    }

    func updateUIViewController(_ picker: UIImagePickerController, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(onCapture: onCapture)
    }

    private func makeOverlay(size: CGSize) -> UIView {
        let overlay = UIView(frame: CGRect(origin: .zero, size: size))
        // Der Overlay darf keine Touches abfangen, sonst ist der Auslöser tot.
        overlay.isUserInteractionEnabled = false
        overlay.backgroundColor = .clear

        if let ghostImage {
            let ghost = UIImageView(image: ghostImage)
            ghost.frame = overlay.bounds
            ghost.contentMode = .scaleAspectFill
            ghost.alpha = 0.35
            overlay.addSubview(ghost)
        }

        let label = UILabel()
        label.text = instruction
        label.numberOfLines = 3
        label.textColor = .white
        label.font = .systemFont(ofSize: 14, weight: .medium)
        label.textAlignment = .center
        label.backgroundColor = UIColor.black.withAlphaComponent(0.55)
        label.frame = CGRect(x: 12, y: 70, width: size.width - 24, height: 66)
        label.layer.cornerRadius = 10
        label.clipsToBounds = true
        overlay.addSubview(label)

        return overlay
    }

    final class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        private let onCapture: (UIImage) -> Void

        init(onCapture: @escaping (UIImage) -> Void) {
            self.onCapture = onCapture
        }

        func imagePickerController(
            _ picker: UIImagePickerController,
            didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey: Any]
        ) {
            if let image = info[.originalImage] as? UIImage {
                onCapture(image)
            }
            picker.dismiss(animated: true)
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            picker.dismiss(animated: true)
        }
    }
}

/// Foto-Timeline je Slot -- immer nur derselbe Slot nebeneinander.
///
/// Ein Vergleich über verschiedene Slots hinweg wäre wertlos, deshalb ist die
/// Timeline strikt nach Slot getrennt.
struct PhotoTimelineView: View {
    @EnvironmentObject private var store: Store
    @State private var slot: PhotoSlot = .chestFront

    private var photos: [PhotoRecord] {
        store.photos.filter { $0.slot == slot }.sorted { $0.takenAt > $1.takenAt }
    }

    var body: some View {
        VStack(spacing: 16) {
            Picker("Slot", selection: $slot) {
                ForEach(PhotoSlot.allCases, id: \.self) { value in
                    Text(value.displayName).tag(value)
                }
            }
            .pickerStyle(.menu)

            if photos.isEmpty {
                ContentUnavailableView(
                    "Keine Fotos in diesem Slot",
                    systemImage: "camera",
                    description: Text("Ohne vergleichbare Fotos macht die Analyse hier keine Aussage.")
                )
            } else {
                ScrollView {
                    LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                        ForEach(photos) { photo in
                            VStack(spacing: 6) {
                                photoThumbnail(photo)
                                Text(photo.takenAt.formatted(date: .abbreviated, time: .omitted))
                                    .font(.system(size: 12))
                                    .foregroundStyle(GymTheme.secondaryText)
                                if let weight = photo.bodyweightAtTime {
                                    Text("\(weight.kgText) kg")
                                        .font(.system(size: 11).monospacedDigit())
                                        .foregroundStyle(GymTheme.secondaryText)
                                }
                            }
                        }
                    }
                }
            }
        }
        .padding(16)
        .navigationTitle("Fotos")
    }

    private func photoThumbnail(_ photo: PhotoRecord) -> some View {
        Group {
            if let image = UIImage(contentsOfFile: store.photoURL(for: photo).path) {
                Image(uiImage: image)
                    .resizable()
                    .aspectRatio(3 / 4, contentMode: .fill)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
            } else {
                RoundedRectangle(cornerRadius: 12)
                    .fill(GymTheme.surface)
                    .aspectRatio(3 / 4, contentMode: .fit)
            }
        }
    }
}
