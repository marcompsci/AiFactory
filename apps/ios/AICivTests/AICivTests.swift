import XCTest
@testable import AICiv

/// Fixtures in AICivTests/Fixtures are real responses captured from the AI Civilization API.
private func fixture(_ name: String) throws -> Data {
    let bundle = Bundle(for: SSEParserTests.self)
    let url = try XCTUnwrap(bundle.url(forResource: name, withExtension: "json"), "missing fixture \(name)")
    return try Data(contentsOf: url)
}

final class SSEParserTests: XCTestCase {
    func testDispatchesOnBlankLineAndTracksId() {
        var p = SSEParser()
        XCTAssertNil(p.consume(line: "id: 7"))
        XCTAssertNil(p.consume(line: "event: envelope"))
        XCTAssertNil(p.consume(line: "data: {\"a\":1}"))
        let msg = p.consume(line: "")
        XCTAssertEqual(msg, SSEParser.Message(id: "7", event: "envelope", data: "{\"a\":1}"))
        XCTAssertEqual(p.lastEventId, "7")
    }

    func testIgnoresKeepaliveCommentsAndCarriageReturns() {
        var p = SSEParser()
        XCTAssertNil(p.consume(line: ": keepalive"))
        XCTAssertNil(p.consume(line: ""))
        XCTAssertNil(p.consume(line: "event: ready\r"))
        XCTAssertNil(p.consume(line: "data: {}\r"))
        XCTAssertEqual(p.consume(line: "\r")?.event, "ready")
    }

    func testJoinsMultipleDataLines() {
        var p = SSEParser()
        _ = p.consume(line: "data: one")
        _ = p.consume(line: "data: two")
        XCTAssertEqual(p.consume(line: "")?.data, "one\ntwo")
    }
}

final class DecodingTests: XCTestCase {
    func testDecodesRealEventsWithSnakeCaseKeys() throws {
        let page = try APIClient.decoder.decode(EventsPage.self, from: fixture("events"))
        XCTAssertFalse(page.events.isEmpty)
        let first = try XCTUnwrap(page.events.first)
        XCTAssertEqual(first.schemaVersion, 1)
        XCTAssertEqual(first.sequence, 1)
        XCTAssertEqual(first.eventType, "mission.created")
        XCTAssertEqual(first.payload.get("kind")?.string, "market_research")
        XCTAssertTrue(first.isSimulation)
    }

    func testDecodesSnapshotWithHierarchy() throws {
        let snap = try APIClient.decoder.decode(Snapshot.self, from: fixture("snapshot"))
        XCTAssertEqual(snap.agents.count, 9)
        let gm = try XCTUnwrap(snap.agents.first { $0.tier == "general_manager" })
        XCTAssertEqual(gm.modelName, "claude-opus-5-5")
        XCTAssertNil(gm.supervisorAgentId, "the General Manager reports to the owner")
        let pip = try XCTUnwrap(snap.agents.first { $0.key == "research_apps" })
        XCTAssertEqual(pip.modelName, "claude-haiku-5-5")
    }

    func testDecodesOwnersTowerDossier() throws {
        let d = try APIClient.decoder.decode(Dossier.self, from: fixture("dossier"))
        XCTAssertTrue(d.awaitingOwner)
        XCTAssertEqual(d.appName, "Steady Focus")
        XCTAssertEqual(d.checklist.count, 12)
        XCTAssertEqual(d.managerReview?.verdict, "APPROVED_FOR_OWNER_REVIEW")
        XCTAssertTrue(d.testedExactBundle)
        XCTAssertEqual(d.bundle?.digest.count, 64)
        XCTAssertTrue(d.findings.allSatisfy { $0.dataMode == "fixture" && $0.sourceUrl.hasPrefix("fixture://") })
    }

    func testOwnerDecisionRequestUsesServerKeys() throws {
        let data = try APIClient.encoder.encode(OwnerDecisionRequest(decision: "APPROVE", artifactDigest: String(repeating: "a", count: 64), note: nil))
        let obj = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(obj["decision"] as? String, "APPROVE")
        XCTAssertNotNil(obj["artifact_digest"])
    }

    func testSnakeToCamel() {
        XCTAssertEqual("opportunity_id".snakeToCamel, "opportunityId")
        XCTAssertEqual("app_name".snakeToCamel, "appName")
        XCTAssertEqual("title".snakeToCamel, "title")
    }
}

final class FinanceTests: XCTestCase {
    func testDecodesARealCostReviewWaitingForTheOwner() throws {
        let d = try APIClient.decoder.decode(FinancePacketDetail.self, from: fixture("finance_packet"))
        XCTAssertEqual(d.packet.status, "OWNER_DECISION")
        XCTAssertEqual(d.packet.origin, "purchase_request")
        XCTAssertTrue(d.packet.isSimulated, "simulated data must stay labeled")
        XCTAssertNotNil(d.packet.summary)
        let open = d.approvals.filter { $0.status == "REQUESTED" }
        XCTAssertEqual(Set(open.compactMap(\.option)), ["recommended", "requested"])
        for a in open {
            XCTAssertEqual(a.payloadHash.count, 64, "the exact-terms fingerprint the server checks")
            XCTAssertEqual(a.actionType, "purchase")
            XCTAssertFalse(a.accountLabel.isEmpty)
        }
    }

    func testDecodesThePacketList() throws {
        let list = try APIClient.decoder.decode(FinancePacketList.self, from: fixture("finance_packets"))
        XCTAssertTrue(list.packets.contains { $0.origin == "fee_detected" })
    }

    func testDecisionRequestUsesServerKeysAndOmitsEmptyFields() throws {
        let data = try APIClient.encoder.encode(PacketDecisionRequest(decision: "APPROVE", approvalId: "a1", payloadHash: String(repeating: "b", count: 64),
                                                                       note: nil, deferDays: nil))
        let obj = try XCTUnwrap(JSONSerialization.jsonObject(with: data) as? [String: Any])
        XCTAssertEqual(obj["approval_id"] as? String, "a1")
        XCTAssertNotNil(obj["payload_hash"])
        XCTAssertNil(obj["note"])
    }

    func testMoneyFormattingUsesMinorUnits() {
        XCTAssertTrue(Format.money(1500).contains("15"))
        XCTAssertFalse(Format.money(1500).contains("1,500"))
    }
}

final class EventLedgerTests: XCTestCase {
    private func event(_ seq: Int, _ type: String, _ payload: [String: JSONValue] = [:]) -> EventEnvelope {
        EventEnvelope(eventId: UUID().uuidString, schemaVersion: 1, organizationId: "o", missionId: nil, agentId: nil, eventType: type,
                      sequence: seq, occurredAt: "2026-10-14T00:00:00Z", correlationId: "c", payload: payload, executionMode: "live")
    }

    func testAppliesInOrderAndIgnoresDuplicates() {
        var l = EventLedger(lastSequence: 10)
        let r = l.ingest([event(12, "b"), event(11, "a"), event(11, "a")])
        XCTAssertEqual(r.applied.map(\.sequence), [11, 12])
        XCTAssertFalse(r.needsReplay)
        XCTAssertEqual(l.lastSequence, 12)
        XCTAssertEqual(l.feed.first?.sequence, 12)
    }

    func testHoldsBackAfterAGapUntilReplayed() {
        var l = EventLedger(lastSequence: 10)
        let r = l.ingest([event(13, "c")])
        XCTAssertTrue(r.needsReplay)
        XCTAssertTrue(r.applied.isEmpty)
        let fill = l.ingest([event(11, "a"), event(12, "b")])
        XCTAssertEqual(fill.applied.map(\.sequence), [11, 12, 13])
        XCTAssertEqual(l.lastSequence, 13)
    }

    func testTracksTheOwnersQueue() {
        var l = EventLedger(lastSequence: 1)
        _ = l.ingest([event(2, "release.owner_approval_requested", ["opportunity_id": .string("o1")])])
        XCTAssertEqual(l.ownerQueue, ["o1"])
        _ = l.ingest([event(3, "release.owner_approved", ["opportunity_id": .string("o1")])])
        XCTAssertTrue(l.ownerQueue.isEmpty)
    }

    func testReplaysTheRealEventFixtureCleanly() throws {
        let page = try APIClient.decoder.decode(EventsPage.self, from: fixture("events"))
        var l = EventLedger()
        let r = l.ingest(page.events.reversed())
        XCTAssertEqual(r.applied.count, page.events.count)
        XCTAssertFalse(r.needsReplay)
    }
}

@MainActor
final class V51Tests: XCTestCase {
    func testPKCEChallengeIsBase64urlSHA256() {
        // expected value computed independently: base64url(hashlib.sha256(verifier).digest()) without padding
        XCTAssertEqual(SupabaseAuth.challenge(for: "dBjftJeZ4CVP-mJ92K9qyhgTx2qmAXOJ2pA5jI8PCyA"), "aL_mP--qzl631jiF2Xi4AMlp8gDwcOckGYR7kDpglv4")
        let v = SupabaseAuth.makeVerifier()
        XCTAssertGreaterThanOrEqual(v.count, 43)
        XCTAssertNil(v.rangeOfCharacter(from: CharacterSet(charactersIn: "+/=")))
    }

    func testAuthorizeURLUsesPKCEAndTheAppCallback() throws {
        let auth = SupabaseAuth(supabaseURL: URL(string: "https://example.supabase.co")!, publishableKey: "sb_publishable_x")
        let url = auth.authorizeURL(provider: "github", challenge: "abc")
        let items = try XCTUnwrap(URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems)
        XCTAssertEqual(url.path, "/auth/v1/authorize")
        XCTAssertEqual(items.first { $0.name == "redirect_to" }?.value, "aiciv://auth-callback")
        XCTAssertEqual(items.first { $0.name == "code_challenge_method" }?.value, "s256")
    }

    func testJSONValueReadsSnakeKeysAndTreatsNullAsAbsent() throws {
        let v = try JSONDecoder().decode(JSONValue.self, from: Data(#"{"cash_minor": 1250, "finance": null, "items": [{"id": "a"}]}"#.utf8))
        XCTAssertEqual(v.get("cash_minor")?.int, 1250)
        XCTAssertNil(v.get("finance"))
        XCTAssertEqual(v.get("items")?.list.first?.id, "a")
        XCTAssertEqual(Money.minor(1250), Money.minor(1250))  // formatting is locale-dependent; just must not crash
    }

    func testSnapshotCarriesDistricts() throws {
        let snap = try APIClient.decoder.decode(Snapshot.self, from: fixture("snapshot"))
        let d = try XCTUnwrap(snap.districts)
        XCTAssertFalse(d.isEmpty)
        XCTAssertTrue(d.contains { $0.id == "owners-tower" })
    }
}


@MainActor
final class ConnectionTests: XCTestCase {
    func testABareMacAddressBecomesAPIAndCityURLs() {
        XCTAssertEqual(AppState.normalize("192.168.1.20", port: 8000), "http://192.168.1.20:8000")
        XCTAssertEqual(AppState.normalize("http://my-mac.local:9000", port: 8000), "http://my-mac.local:9000")
        XCTAssertEqual(AppState.normalize("my-mac.local:8001", port: 8000), "http://my-mac.local:8001")
        XCTAssertTrue(AppState.isLocalhost("http://localhost:3000"))
        XCTAssertFalse(AppState.isLocalhost("http://192.168.1.20:3000"))
    }

    func testCityGetsTheAppsConnectionAsAJSONString() throws {
        let js = CityWebView.connectionScript(apiURL: "http://192.168.1.20:8000", token: "a'b\"c")
        XCTAssertTrue(js.hasPrefix("try { localStorage.setItem('aiciv.connection', [\""))
        let start = try XCTUnwrap(js.range(of: ", ")?.upperBound), end = try XCTUnwrap(js.range(of: "[0])", options: .backwards)?.lowerBound)
        let arr = try JSONSerialization.jsonObject(with: Data(js[start..<end].utf8)) as? [String]
        let obj = try JSONSerialization.jsonObject(with: Data(try XCTUnwrap(arr?.first).utf8)) as? [String: Any]
        XCTAssertEqual(obj?["apiUrl"] as? String, "http://192.168.1.20:8000")
        XCTAssertEqual(obj?["token"] as? String, "a'b\"c")
        XCTAssertEqual(obj?["native"] as? Bool, true)
    }
}
