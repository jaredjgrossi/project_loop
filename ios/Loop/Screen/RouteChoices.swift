import QuartzCore
import SwiftUI

/// Design lab C, "Reading the route" (design-review-v1, problems 2, 4 and 7). Only when the lab
/// switch is on:
/// - the other two of the top three stay on the map after the settle, each with a distance pill;
///   a tap on a pill, on the line, or on the card's eyebrow opens that route;
/// - the card says which route this is and what kind ("1 OF 3 · OUT AND BACK") and names it;
/// - the open sheet lists the way, stretch by stretch;
/// - climb reads in feet and the reason sentence knows about parks.
/// The server sends full details (stats, stretches, profile) for the top route only, so an
/// alternate's card shows its distance, kind and name, and says so.
extension MainModel {
    /// Where the shown route sits in the top three: (1, 3) for the first of three.
    var routePosition: (index: Int, count: Int)? {
        guard let shown = build.shownRank, let i = build.engineTop3.firstIndex(of: shown) else { return nil }
        return (i + 1, build.engineTop3.count)
    }

    /// The other routes can be opened once the route has settled.
    var routesAreChoosable: Bool { DesignLab.shared.routes && build.provisional && build.engineTop3.count > 1 }

    /// Open another of the top three: the line morphs to it and the camera fits it.
    func showRoute(rank: Int) {
        guard routesAreChoosable, rank != build.shownRank, data.candidate(rank: rank) != nil else { return }
        build.show(rank, at: CACurrentMediaTime())
        pickedRank = rank
        clearSelection()
        frameVersion += 1
        Haptics.mileTick()
        routeCameraFree = false
        autoFitRoute(duration: 0.5)
    }

    /// The eyebrow's tap: the next of the three, round again to the first.
    func showNextRoute() {
        guard routesAreChoosable, let shown = build.shownRank, let i = build.engineTop3.firstIndex(of: shown) else { return }
        showRoute(rank: build.engineTop3[(i + 1) % build.engineTop3.count])
    }

    /// Where an alternate's pill goes: the point on it farthest from the shown route, so the pill
    /// marks where the two differ. Two routes that hardly differ fall back to the alternate's
    /// farthest point from the start. Kept until the routes or the shown route change.
    func alternateAnchor(rank: Int) -> GeoPoint? {
        guard let shownRank = build.shownRank, let lead = shown?.line, let alt = data.candidate(rank: rank)?.line else { return nil }
        let key = "\(shownRank)>\(rank)"
        if let hit = alternateAnchors[key] { return hit }
        let leadPts = lead.resampled(count: 96), altPts = alt.resampled(count: 96)
        var anchor = altPts[0], best = -1.0
        for a in altPts {
            var nearest = Double.greatestFiniteMagnitude
            for l in leadPts { nearest = min(nearest, a.distance(to: l)) }
            if nearest > best { best = nearest; anchor = a }
        }
        if best < 80, let first = altPts.first {
            var far = 0.0
            for a in altPts { let d = first.distance(to: a); if d > far { far = d; anchor = a } }
        }
        alternateAnchors[key] = anchor
        return anchor
    }

    /// "1 OF 3 · OUT AND BACK": position and kind (the pool count moves to "How Loop read it").
    var labEyebrowText: String {
        let kind = shown?.kindText ?? ""
        guard build.provisional, let p = routePosition, p.count > 1 else { return kind }
        return kind.isEmpty ? "\(p.index) OF \(p.count)" : "\(p.index) OF \(p.count) · \(kind)"
    }

    /// The route's name on the card.
    var shownTitle: String? { shown.flatMap(RouteTitle.title) }
}

/// A short name for a route: the place from the server's name ("Out-and-back on East River
/// Esplanade" → "East River Esplanade"), or the route's longest stretch when there is no name.
enum RouteTitle {
    private static let kinds = ["out-and-back with a loop", "out-and-back both ways", "out-and-back", "one way,", "one way", "loop"]
    private static let joins = ["with a lap of", "on", "through", "along"]

    static func title(_ c: Candidate) -> String? {
        if let label = c.label, let t = fromLabel(label) { return t }
        guard let d = c.detail else { return nil }
        var total: [String: Double] = [:]
        for s in d.stretches { total[s.name, default: 0] += s.lengthM }
        return total.max { $0.value < $1.value }?.key
    }

    static func fromLabel(_ label: String) -> String? {
        // The generator's own labels carry a heading ("…, heading 148 degrees"); names don't.
        var s = label.components(separatedBy: ", heading").first ?? label
        s = s.trimmingCharacters(in: .whitespaces)
        for k in kinds where s.lowercased().hasPrefix(k) {
            s = String(s.dropFirst(k.count)).trimmingCharacters(in: .whitespaces)
            break
        }
        var lap = false
        for j in joins where s.lowercased().hasPrefix(j + " ") {
            lap = j == "with a lap of"
            s = String(s.dropFirst(j.count + 1))
            break
        }
        guard !s.isEmpty else { return nil }
        if lap { return "A lap of " + s }
        return s.prefix(1).uppercased() + s.dropFirst()
    }
}

/// Distance pills on the other two routes, each at that route's farthest point from the start.
struct AlternatesOverlay: View {
    let model: MainModel

    var body: some View {
        GeometryReader { geo in content(size: geo.size) }
    }

    @ViewBuilder private func content(size: CGSize) -> some View {
        ZStack(alignment: .topLeading) {
            if model.routesAreChoosable, model.zoom >= 11 {
                let placed = placements(in: size)
                ForEach(placed, id: \.rank) { p in
                    Button { model.showRoute(rank: p.rank) } label: {
                        Text(CardText.miles(p.miles))
                            .typeStyle(.label)
                            .foregroundStyle(Palette.ink.color)
                            .padding(.horizontal, 10)
                            .frame(height: 26)
                            .background(Capsule().fill(Palette.surfaceSheet.color))
                            .overlay(Capsule().strokeBorder(Palette.controlBorder.color, lineWidth: 1))
                            .shadow(color: Color(red: 60 / 255, green: 40 / 255, blue: 10 / 255).opacity(0.10), radius: 7, y: 4)
                            .frame(minWidth: Metrics.minTap, minHeight: Metrics.minTap)
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .position(p.point)
                    .accessibilityLabel("Another route, \(CardText.miles(p.miles))\(p.name.map { ", " + $0 } ?? "")")
                    .accessibilityHint("Shows this route")
                    .transition(.opacity)
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .animation(Motion.textArrive, value: model.routesAreChoosable)
    }

    private struct Placement { let rank: Int; let point: CGPoint; let miles: Double; let name: String? }

    /// Each pill sits just off its route's farthest point; a second pill that would land on the
    /// first steps down clear of it.
    private func placements(in size: CGSize) -> [Placement] {
        // A route that runs off screen keeps its pill at the edge nearest it, so it can still be opened.
        let minX: CGFloat = 44, maxX = max(44, size.width - 44)
        let minY = model.headerBottom + 30, maxY = max(minY, size.height - model.sheet.height - 30)
        var out: [Placement] = []
        for rank in model.otherRanks {
            guard let c = model.data.candidate(rank: rank), let far = model.alternateAnchor(rank: rank),
                  var pt = model.screenPoint(far) else { continue }
            pt.y -= 22
            pt.x = min(max(pt.x, minX), maxX)
            pt.y = min(max(pt.y, minY), maxY)
            while out.contains(where: { abs($0.point.x - pt.x) < 70 && abs($0.point.y - pt.y) < 30 }) { pt.y += 32 }
            out.append(Placement(rank: rank, point: pt, miles: c.distanceMi, name: RouteTitle.title(c)))
        }
        return out
    }
}

/// The eyebrow as a control: "1 OF 3 · OUT AND BACK" and three dots. A tap opens the next route.
struct RouteEyebrow: View {
    let model: MainModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        let text = model.labEyebrowText
        let position = model.routesAreChoosable ? model.routePosition : nil
        Button { model.showNextRoute() } label: {
            HStack(spacing: 10) {
                Text(text)
                    .typeStyle(.eyebrow)
                    .foregroundStyle(Palette.inkMuted.color)
                    .contentTransition(.opacity)
                if let p = position {
                    HStack(spacing: 5) {
                        ForEach(1...p.count, id: \.self) { i in
                            Circle()
                                .fill(i == p.index ? Palette.ink.color : Palette.lineControl.color.opacity(0.45))
                                .frame(width: 5, height: 5)
                        }
                    }
                    .accessibilityHidden(true)
                }
            }
            .frame(height: 14)
            // A 44 pt target around a 14 pt line, without moving the layout.
            .padding(.vertical, 15)
            .contentShape(Rectangle())
            .padding(.vertical, -15)
        }
        .buttonStyle(.plain)
        .disabled(position == nil)
        .animation(reduceMotion ? nil : Motion.textArrive, value: text)
        .accessibilityLabel(position.map { "Route \($0.index) of \($0.count), \(model.shown?.kindText.lowercased() ?? "")" } ?? text)
        .accessibilityHint(position == nil ? "" : "Shows the next route")
    }
}

/// "The way": the route as a short list, stretch by stretch, so a runner can hold it in their head.
/// An out-and-back lists the way out, the turn, then "Back the same way".
struct WaySection: View {
    let model: MainModel

    struct Row: Identifiable, Equatable {
        let id: Int
        let name: String
        let kind: DrawKind?
        let miles: Double?
        /// Along-route metres of the row's middle, for selecting it on the map.
        let midM: Double?
    }

    static let maxRows = 7

    /// Neighbouring stretches with one name join; stretches under 60 m fold into the next.
    static func rows(_ d: RouteDetail) -> [Row] {
        let isOutAndBack = d.summary.kind == "out_and_back" && d.turnaround != nil
        let endM = isOutAndBack ? d.turnaround!.alongM : d.line.length
        var merged: [(name: String, kind: DrawKind, from: Double, to: Double)] = []
        for s in d.stretches where s.fromM < endM - 1 {
            let to = min(s.toM, endM)
            if let last = merged.last, last.name == s.name {
                merged[merged.count - 1].to = to
            } else if let last = merged.last, last.to - last.from < 60 {
                merged[merged.count - 1] = (s.name, s.kind, last.from, to)
            } else {
                merged.append((s.name, s.kind, s.fromM, to))
            }
        }
        let perM = d.line.length > 0 ? d.distanceMi / d.line.length : 0
        var out = merged.enumerated().map { i, m in
            Row(id: i, name: m.name, kind: m.kind, miles: (m.to - m.from) * perM, midM: (m.from + m.to) / 2)
        }
        if out.count > maxRows {
            let rest = out.count - (maxRows - 1)
            out = Array(out.prefix(maxRows - 1)) + [Row(id: 900, name: "and \(rest) more", kind: nil, miles: nil, midM: nil)]
        }
        if isOutAndBack, let t = d.turnaround {
            out.append(Row(id: 901, name: "Turn at \(CardText.oneDecimal(t.alongMi)) mi", kind: nil, miles: nil, midM: t.alongM))
            out.append(Row(id: 902, name: "Back the same way", kind: nil, miles: nil, midM: nil))
        }
        return out
    }

    var body: some View {
        if let d = model.shownDetail {
            let rows = Self.rows(d)
            VStack(alignment: .leading, spacing: 0) {
                Text("The way").typeStyle(.eyebrow).foregroundStyle(Palette.inkMuted.color)
                    .padding(.bottom, 4)
                    .accessibilityAddTraits(.isHeader)
                ForEach(rows) { r in
                    CleanTap(hint: r.midM == nil ? "" : "Shows this stretch on the map") {
                        guard let m = r.midM else { return }
                        model.sheet.settle(rest: .open, animated: true)
                        model.selectPoint(alongM: m)
                    } label: {
                        HStack(spacing: 12) {
                            KindSwatch(kind: r.kind)
                            Text(r.name).typeStyle(.body)
                                .foregroundStyle(r.kind == nil ? Palette.inkSoft.color : Palette.ink.color)
                                .lineLimit(1)
                            Spacer(minLength: 8)
                            if let mi = r.miles {
                                Text(CardText.miles(mi)).typeStyle(.label).foregroundStyle(Palette.inkMuted.color)
                            }
                        }
                        .frame(minHeight: Metrics.minTap)
                        .contentShape(Rectangle())
                        .overlay(alignment: .bottom) { Rectangle().fill(Palette.lineHairline.color).frame(height: 1) }
                    }
                }
            }
            .padding(.top, 22)
        }
    }
}

/// A short sample of how a stretch is drawn on the map: waterfront solid and wide, path dashed,
/// street thinner. Never told apart by colour alone.
struct KindSwatch: View {
    let kind: DrawKind?

    var body: some View {
        Canvas { ctx, size in
            guard let kind else { return }
            var p = Path()
            p.move(to: CGPoint(x: 1, y: size.height / 2))
            p.addLine(to: CGPoint(x: size.width - 1, y: size.height / 2))
            switch kind {
            case .waterfront:
                ctx.stroke(p, with: .color(Palette.routeWater.color), style: StrokeStyle(lineWidth: 4.5, lineCap: .round))
            case .path:
                ctx.stroke(p, with: .color(Palette.routePath.color), style: StrokeStyle(lineWidth: 4.5, lineCap: .butt, dash: [6, 4]))
            case .street:
                ctx.stroke(p, with: .color(Palette.routeStreet.color), style: StrokeStyle(lineWidth: 3.5, lineCap: .round))
            }
        }
        .frame(width: 22, height: 10)
        .accessibilityHidden(true)
    }
}

extension CardText {
    /// Lab C: the reason sentence leads with whichever of water or park is largest, so a park
    /// route no longer reads "Mostly on streets".
    static func reasonWithParks(_ s: RouteFile.Summary) -> String? {
        guard let w = s.waterfrontPct.value, let lights = s.lightsPerMile.value else { return reason(s) }
        let water = Int(w.rounded()), park = Int((s.parkPct.value ?? 0).rounded())
        let lead: String
        if water >= 60 { lead = "Mostly by the water" }
        else if park >= 60 { lead = "Mostly through the park" }
        else if water >= 40 { lead = "About half by the water" }
        else if park >= 40 { lead = "About half through the park" }
        else if water + park >= 50 { lead = "About half by water and park" }
        else { lead = "Mostly on streets" }
        return "\(lead): \(oneDecimal(lights)) lights a mile."
    }

    /// Lab C: the same three stats, with climb in feet.
    static func statsInFeet(_ s: RouteFile.Summary) -> [Stat] {
        stats(s).map { st in
            guard st.label == "climb", let m = s.climb.value else { return st }
            return Stat(value: feet(fromMetres: m), label: st.label, trust: st.trust, source: st.source)
        }
    }

    /// Lab C: climb in feet, to the nearest 5.
    static func feet(fromMetres m: Double) -> String {
        let ft = m * 3.28084
        return "\(Int((ft / 5).rounded() * 5)) ft"
    }
}
