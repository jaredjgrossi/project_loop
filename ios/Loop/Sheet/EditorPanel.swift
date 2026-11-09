import SwiftUI

extension MainModel.EditTarget {
    var isUnderstood: Bool { if case .understood = self { return true } else { return false } }
    var field: String { switch self { case let .understood(f), let .filled(f): return f } }
}

/// The small editor for one value: its source, the right control, Done (UI chat, 2026-11-08).
/// Done resends the constraints once the app is wired to the server; until then it updates the
/// sentence and the list here.
struct EditorPanel: View {
    let model: MainModel
    let target: MainModel.EditTarget
    @State private var miles: Double = 3
    @State private var minutes: Int = 7 * 60
    @State private var choice = ""

    private var understood: ReadOut.Understood? { model.readOut?.understood.first { $0.field == target.field } }
    private var filled: ReadOut.Filled? { model.readOut?.filled.first { $0.field == target.field } }

    private var title: String {
        if let u = understood, target.isUnderstood { return "\(u.title) · you said" }
        if let f = filled { return "\(titleFor(f.field)) · \(f.source)" }
        return ""
    }

    private func titleFor(_ field: String) -> String {
        ["start": "Start", "mode": "Mode", "tolerance": "Distance limit", "shape": "Shape"][field] ?? field.capitalized
    }

    private var options: [String] {
        switch target.field {
        case "scenery": return ["By the water", "Some", "Don't mind"]
        case "shape": return ["Any shape", "A loop", "Out and back"]
        case "mode": return ["Training", "Exploring"]
        case "tolerance": return ["Within 5%", "Within 10%"]
        default: return []
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).typeStyle(.eyebrow).foregroundStyle(Palette.inkMuted.color)
            control
            HStack {
                Button("Cancel") { model.editing = nil }
                    .typeStyle(.body).foregroundStyle(Palette.inkMuted.color)
                Spacer()
                Button("Done") { done() }
                    .typeStyle(.bodyStrong).foregroundStyle(Palette.action.color)
            }
            .frame(height: Metrics.minTap)
        }
        .padding(.horizontal, 16).padding(.top, 12).padding(.bottom, 4)
        .frame(width: 280, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 14).fill(Palette.surfaceSheet.color))
        .overlay(RoundedRectangle(cornerRadius: 14).strokeBorder(Palette.lineHairline.color, lineWidth: 1))
        .shadow(color: .black.opacity(0.12), radius: 12, y: 8)
        .frame(maxWidth: .infinity, alignment: target.isUnderstood ? .leading : .center)
        .padding(.horizontal, Metrics.s24)
        .onAppear(perform: load)
    }

    @ViewBuilder private var control: some View {
        switch target.field {
        case "distance":
            stepper(text: "\(CardText.trimmed(miles)) mi",
                    minus: { miles = max(0.5, miles - 0.5) }, plus: { miles = min(30, miles + 0.5) })
        case "time":
            stepper(text: clock(minutes),
                    minus: { minutes = (minutes - 15 + 1440) % 1440 }, plus: { minutes = (minutes + 15) % 1440 })
        case "start":
            Text(understood?.value ?? filled?.detail ?? "")
                .typeStyle(.body).foregroundStyle(Palette.ink.color)
            Text("Choosing another start comes with place search.")
                .typeStyle(.data).foregroundStyle(Palette.inkMuted.color)
        default:
            FlowLayout(spacing: 8, lineSpacing: 8) {
                ForEach(options, id: \.self) { o in
                    Button { choice = o } label: {
                        Text(o).typeStyle(.label)
                            .foregroundStyle(choice == o ? Palette.onAction.color : Palette.ink.color)
                            .padding(.horizontal, 12).frame(height: 34)
                            .background(Capsule().fill(choice == o ? Palette.action.color : Palette.surfaceSunken.color))
                            .frame(height: Metrics.minTap)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private func stepper(text: String, minus: @escaping () -> Void, plus: @escaping () -> Void) -> some View {
        HStack {
            roundButton("minus", label: "Less", action: minus)
            Spacer()
            Text(text).typeStyle(.numeralL).foregroundStyle(Palette.ink.color)
            Spacer()
            roundButton("plus", label: "More", action: plus)
        }
    }

    private func roundButton(_ symbol: String, label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: symbol).font(.system(size: 17, weight: .medium)).foregroundStyle(Palette.ink.color)
                .frame(width: Metrics.minTap, height: Metrics.minTap)
                .overlay(Circle().strokeBorder(Palette.controlBorder.color, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(label)
    }

    private func clock(_ m: Int) -> String {
        let h = m / 60, mm = m % 60, h12 = h % 12 == 0 ? 12 : h % 12
        return mm == 0 ? "\(h12) \(h < 12 ? "am" : "pm")" : "\(h12):\(mm < 10 ? "0" : "")\(mm) \(h < 12 ? "am" : "pm")"
    }

    private func load() {
        if let u = understood, target.isUnderstood {
            if u.field == "distance" { miles = Double(u.value.replacingOccurrences(of: " mi", with: "")) ?? 3 }
            if u.field == "time" {
                let digits = u.value.split(whereSeparator: { !$0.isNumber }).compactMap { Int($0) }
                var h = digits.first ?? 7
                if u.value.contains("pm"), h < 12 { h += 12 }
                minutes = h * 60 + (digits.count > 1 ? digits[1] : 0)
            }
            if u.field == "scenery" { choice = u.value }
        } else if let f = filled {
            choice = options.first { f.main.lowercased().hasPrefix($0.lowercased().prefix(6)) } ?? options.first ?? ""
        }
    }

    private func done() {
        switch target.field {
        case "distance":
            let v = CardText.trimmed(miles)
            model.applyEdit(field: "distance", value: "\(v) mi", phrase: "\(v) mile\(miles == 1 ? "" : "s")")
        case "time":
            model.applyEdit(field: "time", value: clock(minutes), phrase: "at \(clock(minutes))")
        case "scenery":
            let phrase = ["By the water": "by the water", "Some": "with some scenery", "Don't mind": "anywhere"][choice] ?? choice
            model.applyEdit(field: "scenery", value: choice, phrase: phrase)
        default:
            if var r = model.readOut, let i = r.filled.firstIndex(where: { $0.field == target.field }), !choice.isEmpty {
                let f = r.filled[i]
                let main = target.field == "tolerance" ? "\(choice) of the distance" : target.field == "mode" ? choice : choice
                r.filled[i] = .init(field: f.field, main: main, detail: f.detail, source: "you said")
                model.readOut = r
            }
            model.editing = nil
        }
    }
}
