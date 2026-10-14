import Foundation

/// Incremental Server-Sent Events parser (WHATWG spec subset: id, event, data, comments, blank-line dispatch).
/// Pure value type so it can be unit tested without a network.
struct SSEParser {
    struct Message: Equatable {
        var id: String?
        var event: String
        var data: String
    }

    private var id: String?
    private var event: String?
    private var data: [String] = []
    private(set) var lastEventId: String?

    /// Feed one line (without the trailing newline). Returns a message when a blank line completes one.
    mutating func consume(line raw: String) -> Message? {
        let line = raw.hasSuffix("\r") ? String(raw.dropLast()) : raw
        if line.isEmpty {
            defer { id = nil; event = nil; data = [] }
            guard !data.isEmpty || event != nil else { return nil }
            if let id { lastEventId = id }
            return Message(id: id, event: event ?? "message", data: data.joined(separator: "\n"))
        }
        if line.hasPrefix(":") { return nil } // keepalive comment
        let field: Substring
        var value: Substring = ""
        if let colon = line.firstIndex(of: ":") {
            field = line[line.startIndex..<colon]
            value = line[line.index(after: colon)...]
            if value.hasPrefix(" ") { value = value.dropFirst() }
        } else {
            field = Substring(line)
        }
        switch field {
        case "id": id = String(value)
        case "event": event = String(value)
        case "data": data.append(String(value))
        default: break
        }
        return nil
    }
}
