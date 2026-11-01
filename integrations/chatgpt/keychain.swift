import Foundation
import Security
import CryptoKit

// Key bytes never leave this process. Only ciphertext/plaintext crosses stdio.
func key(create: Bool) throws -> SymmetricKey {
    let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: "chat.maibot.multimodal-gateway",
        kSecAttrAccount as String: "chatgpt-aes-v1"]
    var lookup = query
    lookup[kSecReturnData as String] = true
    lookup[kSecMatchLimit as String] = kSecMatchLimitOne
    var item: CFTypeRef?
    let status = SecItemCopyMatching(lookup as CFDictionary, &item)
    if status == errSecSuccess, let data = item as? Data, data.count == 32 {
        return SymmetricKey(data: data)
    }
    guard status == errSecItemNotFound && create else { throw NSError(domain: "keychain", code: Int(status)) }
    var bytes = Data(count: 32)
    let randomStatus = bytes.withUnsafeMutableBytes { SecRandomCopyBytes(kSecRandomDefault, 32, $0.baseAddress!) }
    guard randomStatus == errSecSuccess else { throw NSError(domain: "random", code: Int(randomStatus)) }
    var add = query
    add[kSecValueData as String] = bytes
    add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
    let added = SecItemAdd(add as CFDictionary, nil)
    guard added == errSecSuccess else { throw NSError(domain: "keychain", code: Int(added)) }
    return SymmetricKey(data: bytes)
}
do {
    guard CommandLine.arguments.count == 2 else { throw NSError(domain: "usage", code: 1) }
    let op = CommandLine.arguments[1]
    let input = FileHandle.standardInput.readDataToEndOfFile()
    guard input.count <= 4 * 1024 * 1024 else { throw NSError(domain: "size", code: 1) }
    let output: Data
    if op == "encrypt" {
        let box = try AES.GCM.seal(input, using: key(create: true))
        output = box.combined!
    } else if op == "decrypt" {
        output = try AES.GCM.open(AES.GCM.SealedBox(combined: input), using: key(create: false))
    } else { throw NSError(domain: "usage", code: 1) }
    FileHandle.standardOutput.write(output)
} catch {
    FileHandle.standardError.write(Data("Keychain encryption unavailable. Unlock your login keychain.\n".utf8))
    exit(1)
}
