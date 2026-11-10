import Foundation
import Security

/// The Loop token, kept in the Keychain as a generic password (never in the bundle, the xcconfig,
/// git or a log). Pasted once on the token screen.
enum TokenStore {
    private static let service = "com.jaredgrossi.loop.api"
    private static let account = "loop-token"

    private static var query: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: account]
    }

    static func load() -> String? {
        var q = query
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: AnyObject?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess,
              let data = out as? Data, let token = String(data: data, encoding: .utf8), !token.isEmpty else { return nil }
        return token
    }

    @discardableResult
    static func save(_ token: String) -> Bool {
        let clean = token.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !clean.isEmpty else { return false }
        delete()
        var q = query
        q[kSecValueData as String] = Data(clean.utf8)
        q[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        return SecItemAdd(q as CFDictionary, nil) == errSecSuccess
    }

    static func delete() {
        SecItemDelete(query as CFDictionary)
    }
}
