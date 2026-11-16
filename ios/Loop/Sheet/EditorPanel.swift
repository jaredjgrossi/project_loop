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
                // Each is a 44 pt target (they were as tall as their text), and Cancel is ink, like
                // the Cancel beside the field.
                Button { model.editing = nil } label: {
                    Text("Cancel").typeStyle(.body).foregroundStyle(Palette.ink.color)
                        .frame(minWidth: Metrics.minTap, minHeight: Metrics.minTap, alignment: .leading)
                        .contentShape(Rectangle())
                }
                Spacer()
                Button { done() } label: {
                    Text("Done").typeStyle(.bodyStrong).foregroundStyle(Palette.action.color).demoTarget("editorDone")
                        .frame(minWidth: Metrics.minTap, minHeight: Metrics.minTap, alignment: .trailing)
                        .contentShape(Rectangle())
                }
            }
            .buttonStyle(.plain)
        }
        .padding(.horizontal, 16).padding(.top, 12).padding(.bottom, 4)
        .frame(width: 280, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Palette.surfaceSheet.color))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Palette.lineHairline.color, lineWidth: 1))
        // The sheets' warm shadow, not neutral black.
        .shadow(color: Color(red: 60 / 255, green: 40 / 255, blue: 10 / 255).opacity(0.14), radius: 12, y: 8)
        .frame(maxWidth: .infinity, alignment: target.isUnderstood ? .leading : .center)
        .padding(.horizontal, Metrics.s24)
        .onAppear(perform: load)
        #if DEBUG
        .onChange(of: model.demoEditorPlus) { _, _ in if target.field == "distance" { miles = min(30, miles + 0.5) } }
        .onChange(of: model.demoEditorDone) { _, _ in done() }
        #endif
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
                .typeStyle(.label).foregroundStyle(Palette.inkMuted.color)
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
            roundButton("plus", label: "More", action: plus).demoTarget("editorPlus")
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
            // Live: start from the value the server holds.
            let wire: [String: String] = ["any": "Any shape", "loop": "A loop", "out_and_back": "Out and back",
                                          "training": "Training", "exploring": "Exploring"]
            let key = ["shape": "shape", "mode": "mode"][f.field]
            if let key, case let .string(v)? = model.liveConstraints?[key], let o = wire[v] { choice = o }
        }
    }

    private func done() {
        switch target.field {
        case "distance":
            let v = CardText.trimmed(miles)
            model.applyEdit(field: "distance", value: "\(v) mi", phrase: "\(v) mile\(miles == 1 ? "" : "s")",
                            constraint: ("distance_mi", .number(miles)))
        case "time":
            let hhmm = String(format: "%02d:%02d", minutes / 60, minutes % 60)
            model.applyEdit(field: "time", value: clock(minutes), phrase: "at \(clock(minutes))",
                            constraint: ("start_time", .string(hhmm)))
        case "scenery":
            let phrase = ["By the water": "by the water", "Some": "with some scenery", "Don't mind": "anywhere"][choice] ?? choice
            let wire = ["By the water": "park_or_water", "Some": "some", "Don't mind": "dont_mind"][choice] ?? "some"
            model.applyEdit(field: "scenery", value: choice, phrase: phrase, constraint: ("scenery", .string(wire)))
        case "shape", "mode", "tolerance":
            // RunConstraints values (api/constraints.py): shape loop | out_and_back | any;
            // mode training | exploring; tolerance_pct.
            let wire: (String, JSONValue)? = {
                switch target.field {
                case "shape": return ["Any shape": ("shape", .string("any")), "A loop": ("shape", .string("loop")),
                                      "Out and back": ("shape", .string("out_and_back"))][choice]
                case "mode": return ["Training": ("mode", .string("training")), "Exploring": ("mode", .string("exploring"))][choice]
                default: return ["Within 5%": ("tolerance_pct", .number(5)), "Within 10%": ("tolerance_pct", .number(10))][choice]
                }
            }()
            if model.liveMode, let wire, !choice.isEmpty {
                model.applyEdit(field: target.field, value: choice, phrase: nil, constraint: wire)
                return
            }
            fallthrough
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
