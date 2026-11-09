import Foundation
import Security
import CryptoKit

// Private key bytes use pipes between this helper and the Python client.
// Never invoke "read" directly in a terminal or log its stdout.
@main
enum IdentityStore {
    static let service = "local.neural-band-poc.identity"

    static func fail(_ message: String) -> Never {
        FileHandle.standardError.write(Data((message + "\n").utf8))
        exit(1)
    }

    static func main() {
        let args = CommandLine.arguments
        guard args.count == 3, ["read", "store"].contains(args[1]),
              !args[2].isEmpty else { fail("Invalid identity-store arguments") }
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: args[2]
        ]
        if args[1] == "store" {
            let data = FileHandle.standardInput.readDataToEndOfFile()
            guard data.count == 32, (try? P256.Signing.PrivateKey(rawRepresentation: data)) != nil else {
                fail("Expected a P-256 private key")
            }
            var item = query
            item[kSecValueData as String] = data
            item[kSecAttrLabel as String] = "Neural Band owner identity"
            item[kSecAttrAccessible as String] = kSecAttrAccessibleWhenUnlockedThisDeviceOnly
            let status = SecItemAdd(item as CFDictionary, nil)
            // Immutable records: never overwrite an existing working identity.
            if status != errSecSuccess && status != errSecDuplicateItem {
                fail("Keychain save failed (OSStatus \(status))")
            }
        }
        var read = query
        read[kSecReturnData as String] = true
        read[kSecMatchLimit as String] = kSecMatchLimitOne
        var value: AnyObject?
        let status = SecItemCopyMatching(read as CFDictionary, &value)
        guard status == errSecSuccess, let data = value as? Data, data.count == 32 else {
            fail("Keychain read failed (OSStatus \(status)); unlock your login keychain and allow the helper")
        }
        // The caller verifies the public-key fingerprint after both store/read.
        FileHandle.standardOutput.write(data)
    }
}
