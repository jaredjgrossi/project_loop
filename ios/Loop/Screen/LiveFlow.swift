import Foundation
import QuartzCore
import SwiftUI
import UIKit

/// A plain message where a spinner would be: the server is unreachable, or it sent an error.
struct LiveNotice: Equatable {
    let text: String
    /// Offer "Try again" (unreachable, engine_unavailable).
    let canRetry: Bool
}

/// Live builds from the Phase 3 server (`docs/phase3/ios-wiring.md`): parsed → candidates → top3 →
/// provisional → final → done, driving the wait, reach ring, outlines, route draw and settle that
/// the bundled-file replay drives otherwise. Questions pause the build until answered.
extension MainModel {
    /// Copy for the two messages the server can't send itself. The UI chat owns wording.
    enum LiveCopy {
        static let unreachable = "Can't reach Loop right now."
        static let tokenWrong = "That token didn't work. Paste it again."
        static let noRoute = "No route came back for that."
    }

    /// No `parsed` within this long after sending (the parse is 1.7 s median, 3.1 s p90): give up.
    static let parsedTimeout: TimeInterval = 8
    /// After `parsed`, this long with no line at all (the server pings every 15 s): give up.
    static let silenceTimeout: TimeInterval = 20

    /// GET /v1/health at launch (and on Try again): the landing sheet says when it fails.
    func checkHealth() {
        guard let base = LoopAPI.baseURL else { return }
        Task { @MainActor [weak self] in
            let ok = await LoopAPI.health(base: base)
            self?.serverDown = !ok
        }
    }

    /// Never wait forever: no `parsed` in 8 s, or 20 s of silence later, stops the wait with a
    /// plain line and Try again.
    private func armWatchdog() {
        liveWatchdog?.cancel()
        liveWatchdog = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(for: .seconds(0.5))
                guard let self, !Task.isCancelled else { return }
                guard self.liveMode, self.pendingQuestion == nil, self.liveNotice == nil,
                      [.reading, .building].contains(self.stage) else { return }
                let now = CACurrentMediaTime()
                let stalled = self.liveParsedAt == nil
                    ? now - self.liveSentAt > Self.parsedTimeout
                    : now - self.liveLastActivity > Self.silenceTimeout
                if stalled {
                    self.liveTask?.cancel()
                    self.showNotice(LiveNotice(text: LiveCopy.unreachable, canRetry: true))
                    return
                }
            }
        }
    }

    /// The camera while Loop reads: the push-in has started (send); drift in slowly until `parsed`
    /// arrives (1.7 s median, 3.1 s p90). The pull-back waits for the push-in to finish (1.2 s), so
    /// a fast parse never cuts it off and a slow one still has the map moving.
    func startLive(sentence: String, shown: String, api: LoopAPI, z0: Double, reduceMotion: Bool,
                   body: RunRequest? = nil) {
        liveMode = true
        if !liveResending { liveExpiredRetried = false }
        liveResending = false
        liveReachM = nil
        liveKeys = [:]
        liveOutlines = []
        liveRouteId = nil
        liveParseId = nil
        liveParsedAt = nil
        liveSentence = sentence
        liveSentAt = CACurrentMediaTime()
        data = LoopData(request: liveRequestCard(chips: [], startHour: ""), candidates: [], bestOf: 0)
        flow = Task { @MainActor [weak self] in
            try? await Task.sleep(for: .seconds(1.2))
            guard let self, !Task.isCancelled, self.liveParsedAt == nil else { return }
            self.requestCamera(.at(self.location, zoom: z0 + 1.7), animated: true, duration: 3.3)
        }
        if body?.constraints != nil || body?.mode == "exact" {
            // A chip edit: no Claude, `parsed` comes back at once, so there's no push-in to wait for.
            flow?.cancel()
            liveSentAt = CACurrentMediaTime() - 1.2
        }
        runLive(api: api, body: body ?? makeRequest(text: sentence, answer: nil), shown: shown, reduceMotion: reduceMotion)
    }

    /// A chip edit (decision: resend `constraints`): set the field, drop the chip's span and its
    /// source (an edited value is said, but not in the sentence), and rebuild from `parsed`.
    @discardableResult
    func rebuildLive(field: String, key: String, value: JSONValue) -> Bool {
        guard let api = LoopAPI.live, let parsed = liveConstraints else { return false }
        let chipId = readOut?.understood.first { $0.field == field }?.chipId
            ?? readOut?.filled.first { $0.field == field }?.chipId
        let c = Self.edited(parsed, key: key, value: value, chipId: chipId)
        let reduceMotion = UIAccessibility.isReduceMotionEnabled
        exitEditMode()
        clearSelection()
        playbackCancel()
        flow?.cancel()
        pendingQuestion = nil
        liveNotice = nil
        build = BuildState()
        drawnFraction = 0
        frameVersion += 1
        reachStart = nil; reachFadeStart = nil; candidatesStart = nil
        withAnimation(reduceMotion ? nil : .timingCurve(0.2, 0, 0, 1, duration: 0.4)) { sheetShown = false }
        sheet.settle(open: false, animated: false)
        stage = .reading
        locationPulsing = !reduceMotion
        routeCameraFree = false
        recordOnSettle = requestText.map { RunStore.sentence($0) }
        let shown = requestText ?? liveSentence
        startLive(sentence: liveSentence, shown: shown, api: api, z0: zoom, reduceMotion: reduceMotion,
                  body: makeRequest(text: nil, answer: nil, constraints: c))
        return true
    }

    /// "Run again" (decision 043): `{route_id, mode: "exact"}`; the stream is parsed, final, done.
    func runAgainLive(routeId: String, request: String) {
        guard let api = LoopAPI.live else { return }
        let reduceMotion = UIAccessibility.isReduceMotionEnabled
        exitEditMode()
        clearSelection()
        playbackCancel()
        flow?.cancel()
        pendingQuestion = nil
        liveNotice = nil
        rating = nil
        cardMode = .normal
        build = BuildState()
        drawnFraction = 0
        frameVersion += 1
        reachStart = nil; reachFadeStart = nil; candidatesStart = nil
        withAnimation(reduceMotion ? nil : .timingCurve(0.2, 0, 0, 1, duration: 0.4)) { sheetShown = false }
        sheet.settle(open: false, animated: false)
        stage = .reading
        locationPulsing = !reduceMotion
        routeCameraFree = false
        liveSentence = request
        var body = makeRequest(text: nil, answer: nil)
        body.routeId = routeId
        body.mode = "exact"
        startLive(sentence: request, shown: requestText ?? request, api: api, z0: zoom, reduceMotion: reduceMotion, body: body)
    }

    /// The parse's constraints with one field changed, the chip's span and the field's source gone.
    nonisolated static func edited(_ constraints: JSONValue, key: String, value: JSONValue, chipId: String?) -> JSONValue {
        var c = constraints
        c[key] = value
        if let chipId, case var .object(spans)? = c["spans"] {
            spans[chipId] = nil
            c["spans"] = .object(spans)
        }
        if case var .object(sources)? = c["sources"] {
            sources[key] = nil
            c["sources"] = .object(sources)
        }
        return c
    }

    private func makeRequest(text: String?, answer: RunRequest.Answer?, constraints: JSONValue? = nil) -> RunRequest {
        RunRequest(text: text, answer: answer, constraints: constraints,
                   routeId: constraints != nil ? liveBuildId : nil,
                   shape: text != nil && shapeTouched ? pickedShape.rawValue : nil,
                   client: RunRequest.client(location: LoopAPI.baseURL != nil ? locationProvider.requestLocation : nil),
                   profile: RunRequest.Profile(runs.profile),
                   recentRoutes: runs.recentRoutesPayload)
    }

    private func runLive(api: LoopAPI, body: RunRequest, shown: String, reduceMotion: Bool) {
        liveTask?.cancel()
        liveLastBody = body
        liveLastActivity = CACurrentMediaTime()
        armWatchdog()
        liveTask = Task { @MainActor [weak self] in
            do {
                for try await event in api.run(body) {
                    guard let self, !Task.isCancelled else { return }
                    self.liveLastActivity = CACurrentMediaTime()
                    await self.handleLive(event, shown: shown, reduceMotion: reduceMotion)
                }
            } catch LoopAPI.Failure.unauthorized {
                guard let self, !Task.isCancelled else { return }
                TokenStore.delete()
                self.tokenMessage = LiveCopy.tokenWrong
                self.needsToken = true
                self.showNotice(LiveNotice(text: LiveCopy.tokenWrong, canRetry: true))
            } catch {
                guard let self, !Task.isCancelled else { return }
                self.showNotice(LiveNotice(text: LiveCopy.unreachable, canRetry: true))
            }
        }
    }

    private func handleLive(_ event: ServerEvent, shown: String, reduceMotion: Bool) async {
        switch event {
        case let .parsed(p):
            liveParseId = p.parseId
            if let c = p.constraints { liveConstraints = c }
            liveReachM = p.reachM
            data = LoopData(request: liveRequestCard(chips: p.chips, startHour: ""), candidates: data.candidates, bestOf: 0)
            // Let the push-in finish before pulling back.
            let elapsed = CACurrentMediaTime() - liveSentAt
            if elapsed < 1.2 { try? await Task.sleep(for: .seconds(1.2 - elapsed)) }
            guard !Task.isCancelled else { return }
            liveParsedAt = CACurrentMediaTime()
            flow?.cancel()
            readOut = ReadOut(parsed: p, sentence: shown)
            if let q = p.question {
                showQuestion(q, parseId: p.parseId)
                return
            }
            let t = CACurrentMediaTime()
            if let reach = p.reachM, reach > 0 {
                reachStart = reduceMotion ? t - 10 : t
                requestCamera(.circle(location, radiusM: reach), animated: true, duration: 1.0)
            }
            candidatesStart = reduceMotion ? t - 10 : t
            frameVersion += 1

        case let .candidates(c):
            let now = CACurrentMediaTime()
            for o in c.candidates where o.points.count >= 2 {
                liveOutlines.append((o.points.map { GeoPoint(lon: $0[0], lat: $0[1]) }, now))
            }
            if liveOutlines.count > 120 { liveOutlines.removeFirst(liveOutlines.count - 120) }
            frameVersion += 1

        case let .top3(r):
            receiveLiveRoutes(r.routes, provisional: false)

        case let .provisional(r):
            receiveLiveRoutes(r.routes, provisional: true)
            settleLive(reduceMotion: reduceMotion)

        case let .final(f, raw):
            receiveFinal(f, raw: raw, reduceMotion: reduceMotion)

        case let .question(q):
            showQuestion(q, parseId: q.parseId ?? liveParseId)

        case let .error(code, text):
            if code == "expired", !liveExpiredRetried {
                // The question was open too long, or the server restarted: resend once.
                liveExpiredRetried = true
                liveResending = true
                send(liveSentence, reduceMotion: reduceMotion)
                return
            }
            showNotice(LiveNotice(text: text.isEmpty ? LiveCopy.unreachable : text,
                                  canRetry: code == "engine_unavailable" || code == "bad_final"))

        case .planned, .done, .other:
            break
        }
    }

    /// The eyebrow's mode and the crowd sentence's hour, from the chips (shown as sent).
    private func liveRequestCard(chips: [ServerEvent.Chip], startHour: String) -> RequestCard {
        let mode = chips.first { $0.field == "mode" }?.text ?? ""
        return RequestCard(text: liveSentence, provenance: "", startHourText: startHour, mode: mode)
    }

    private func key(for id: String?, rank: Int) -> Int {
        let k = id ?? "rank-\(rank)"
        if let existing = liveKeys[k] { return existing }
        let next = (liveKeys.values.max() ?? 0) + 1
        liveKeys[k] = next
        return next
    }

    /// `top3` or `provisional`: outlines and distances (no card details until `final`).
    private func receiveLiveRoutes(_ routes: [RouteFile.TopCandidate], provisional: Bool) {
        let ordered = routes.sorted { $0.rank < $1.rank }
        var byKey = Dictionary(uniqueKeysWithValues: data.candidates.map { ($0.rank, $0) })
        var keys: [Int] = []
        for r in ordered {
            guard let pts = r.geometry.lineString, pts.count >= 2 else { continue }
            let k = key(for: r.id, rank: r.rank)
            keys.append(k)
            if byKey[k] == nil {
                byKey[k] = Candidate(rank: k, line: Polyline(pts), distanceMi: r.distance.miles,
                                     distanceTrust: Trust(r.distance.status), distanceSource: r.distance.source,
                                     kindText: CardText.kindText(r.kind), detail: nil)
            }
        }
        guard !keys.isEmpty else { return }
        data = LoopData(request: data.request, candidates: byKey.values.sorted { $0.rank < $1.rank }, bestOf: data.bestOf)
        let first = build.shownRank == nil
        receiveEvent(.top3(keys), at: CACurrentMediaTime())
        if first {
            stage = .building
            locationPulsing = false
            requestCamera(.overview, animated: true, duration: 0.9)
        }
    }

    /// The settle moment (decision 018): ring and outlines fade, the card rises.
    private func settleLive(reduceMotion: Bool) {
        guard !build.provisional else { return }
        reachFadeStart = CACurrentMediaTime()
        receiveEvent(.provisional, at: CACurrentMediaTime())
        withAnimation(reduceMotion ? nil : Motion.sheetSettle) { sheetShown = true }
    }

    /// `final`: the #1 in full (card details, stretches, miles), the final top 3 and "Best of N".
    private func receiveFinal(_ f: ServerEvent.Final, raw: Data, reduceMotion: Bool) {
        guard let route = f.route, let first = route.features.first else {
            settleLive(reduceMotion: reduceMotion)
            let text = f.notes?.first?.text ?? LiveCopy.noRoute
            showNotice(LiveNotice(text: text, canRetry: false))
            return
        }
        let start = readOut?.understood.first { $0.field == "start" }?.value ?? "the start"
        let file = RouteFile(about: .init(generatedAt: ISO8601DateFormatter().string(from: Date()), start: start),
                             request: first.properties.request ?? [],
                             route: route, top3: f.routes,
                             pool: f.pool ?? .init(candidates: f.poolSize ?? 0, bestOf: f.poolSize ?? 0))
        guard let built = try? LoopData(file: file) else {
            showNotice(LiveNotice(text: LiveCopy.noRoute, canRetry: true))
            return
        }
        // Keep each route's key, so nothing redraws or jumps.
        let ids = Dictionary(uniqueKeysWithValues: f.routes.map { ($0.rank, $0.id) })
        let remapped = built.candidates.map { c in
            Candidate(rank: key(for: ids[c.rank] ?? nil, rank: c.rank), line: c.line, distanceMi: c.distanceMi,
                      distanceTrust: c.distanceTrust, distanceSource: c.distanceSource,
                      kindText: c.kindText, detail: c.detail)
        }
        let keys = f.routes.sorted { $0.rank < $1.rank }.map { key(for: $0.id, rank: $0.rank) }
        let hour = built.request.startHourText
        data = LoopData(request: liveRequestCard(chips: [], startHour: hour.isEmpty ? "" : hour)
                            .withMode(data.request.mode),
                        candidates: remapped, bestOf: built.bestOf)
        liveRouteId = f.routes.first { $0.rank == 1 }?.id ?? f.routeId
        liveBuildId = f.routeId
        // Keep the route on the phone (Save, History and the return prompt draw it again from here).
        let archiveKey = liveRouteId ?? f.routeId ?? UUID().uuidString
        RouteArchive.save(key: archiveKey, finalJSON: raw)
        if let notes = f.notes, !notes.isEmpty, var r = readOut {
            r.notes += notes.map { ReadOut.Note(key: $0.key ?? "", text: $0.text, trust: $0.trust ?? "") }
            readOut = r
        }
        settleLive(reduceMotion: reduceMotion)
        receiveEvent(.final(keys), at: CACurrentMediaTime())
        stage = .settled
        currentRoute = identityOfShown(archive: archiveKey, routeId: liveRouteId)
        cardMode = .normal
        if let r = currentRoute { runs.noteViewed(r) }
        afterSettle?()
        afterSettle = nil
        if let request = recordOnSettle, let shown = self.shown {
            recordOnSettle = nil
            runs.addRecent(request: request, distanceMi: shown.distanceMi, line: shown.line, serverId: liveRouteId)
        }
    }

    // MARK: Questions

    private func showQuestion(_ q: ServerEvent.Question, parseId: String?) {
        flow?.cancel()
        stage = .reading
        locationPulsing = true
        pendingQuestion = ServerEvent.Question(parseId: parseId, id: q.id, about: q.about, from: q.from, text: q.text,
                                               options: q.options, allowText: q.allowText, chipId: q.chipId)
    }

    /// × on the question: no answer is forced. The build stops and the sentence opens for editing
    /// (go sends it again; the wordmark goes home).
    func cancelQuestion() {
        pendingQuestion = nil
        liveTask?.cancel()
        flow?.cancel()
        locationPulsing = false
        if reachStart != nil { reachFadeStart = CACurrentMediaTime() }
        frameVersion += 1
        stage = .settled
        editMode = true
        editingText = true
    }

    /// A tapped option or typed text: a new request with `answer`; the stream picks up at `parsed`.
    func answerQuestion(optionId: String?, text: String?) {
        guard let q = pendingQuestion, let parseId = q.parseId, let api = LoopAPI.live else { return }
        pendingQuestion = nil
        liveNotice = nil
        liveSentAt = CACurrentMediaTime() - 1.2   // no push-in to wait for
        liveParsedAt = nil
        let answer = RunRequest.Answer(parseId: parseId, questionId: q.id, optionId: optionId,
                                       text: optionId == nil ? text : nil)
        let shown = requestText ?? liveSentence
        runLive(api: api, body: makeRequest(text: nil, answer: answer), shown: shown,
                reduceMotion: UIAccessibility.isReduceMotionEnabled)
    }

    // MARK: Notices and the token

    private func showNotice(_ n: LiveNotice) {
        flow?.cancel()
        locationPulsing = false
        reachFadeStart = reachStart == nil ? nil : CACurrentMediaTime()
        frameVersion += 1
        liveNotice = n
    }

    /// "Try again": the same request again (a chip edit's constraints, or the text).
    func retryLive() {
        liveNotice = nil
        serverDown = false
        if needsToken { return }
        liveExpiredRetried = false
        if let body = liveLastBody, body.constraints != nil, let api = LoopAPI.live {
            stage = .reading
            locationPulsing = !UIAccessibility.isReduceMotionEnabled
            startLive(sentence: liveSentence, shown: requestText ?? liveSentence, api: api, z0: zoom,
                      reduceMotion: UIAccessibility.isReduceMotionEnabled, body: body)
            return
        }
        send(liveSentence, reduceMotion: UIAccessibility.isReduceMotionEnabled)
    }

    /// The token screen saved a token.
    func tokenSaved(_ token: String) -> Bool {
        guard TokenStore.save(token) else { return false }
        needsToken = false
        tokenMessage = nil
        return true
    }
}

extension RequestCard {
    func withMode(_ mode: String) -> RequestCard {
        RequestCard(text: text, provenance: provenance, startHourText: startHourText, mode: mode)
    }
}
