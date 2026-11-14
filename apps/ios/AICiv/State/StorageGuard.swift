import Foundation
import WebKit

/// V6.89: when the phone is nearly full, AI Civ clears what it can safely rebuild (its own network and web caches,
/// temporary files) and says so, instead of failing with "no space left on device". Your tasks and settings live on
/// your Mac and in the Keychain, so nothing you made is touched.
@MainActor
enum StorageGuard {
    /// Below this, the app trims its caches and shows a notice.
    static let lowBytes: Int64 = 1_000_000_000

    struct Report: Equatable {
        let freeBytes: Int64
        let clearedBytes: Int64
        var free: String { ByteCountFormatter.string(fromByteCount: freeBytes, countStyle: .file) }
        var cleared: String { ByteCountFormatter.string(fromByteCount: clearedBytes, countStyle: .file) }
    }

    /// Smaller caches from the start, so the app itself never takes much room.
    static func limitCaches() {
        URLCache.shared = URLCache(memoryCapacity: 8 * 1024 * 1024, diskCapacity: 50 * 1024 * 1024)
    }

    static func freeBytes() -> Int64? {
        let home = URL(fileURLWithPath: NSHomeDirectory())
        let v = try? home.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey, .volumeAvailableCapacityKey])
        if let important = v?.volumeAvailableCapacityForImportantUsage, important > 0 { return important }
        return v?.volumeAvailableCapacity.map(Int64.init)
    }

    /// Checks the free space; when it's low, clears the app's caches. Returns a report only when space was low.
    static func check() async -> Report? {
        guard let free = freeBytes(), free < lowBytes else { return nil }
        let before = usedByCaches()
        // through the caches' own APIs (their files may be open), plus the app's temporary folder
        URLCache.shared.removeAllCachedResponses()
        clear(FileManager.default.temporaryDirectory)
        await WKWebsiteDataStore.default().removeData(ofTypes: [WKWebsiteDataTypeDiskCache, WKWebsiteDataTypeMemoryCache],
                                                      modifiedSince: .distantPast)
        let after = usedByCaches()
        return Report(freeBytes: freeBytes() ?? free, clearedBytes: max(0, before - after))
    }

    private static func usedByCaches() -> Int64 {
        var total = Int64(URLCache.shared.currentDiskUsage)
        let e = FileManager.default.enumerator(at: FileManager.default.temporaryDirectory, includingPropertiesForKeys: [.totalFileAllocatedSizeKey])
        while let f = e?.nextObject() as? URL {
            total += Int64((try? f.resourceValues(forKeys: [.totalFileAllocatedSizeKey]))?.totalFileAllocatedSize ?? 0)
        }
        return total
    }

    /// Deletes the contents of the app's own temporary folder (never the folder itself, never anything else).
    private static func clear(_ dir: URL) {
        let items = (try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil)) ?? []
        for item in items { try? FileManager.default.removeItem(at: item) }
    }
}
