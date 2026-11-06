import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { Sha256 } from "../src/sha256.js";

const utf8 = (s: string) => new TextEncoder().encode(s);

describe("SHA-256 (FIPS 180-4), the hash of sections 3.6 and 3.7", () => {
  it("gives the FIPS 180-2 example digests", () => {
    expect(new Sha256().update(utf8("abc")).hex()).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
    expect(new Sha256().update(utf8("abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq")).hex()).toBe(
      "248d6a61d20638b8e5c026930c3e6039a33ce45964ff2167f6ecedd419db06c1",
    );
    expect(new Sha256().hex()).toBe("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855");
    const million = new Sha256();
    const a = utf8("a".repeat(1000));
    for (let i = 0; i < 1000; i++) million.update(a);
    expect(million.hex()).toBe("cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0");
  });

  it("agrees with node:crypto on every length around the block and padding edges, fed in any pieces", () => {
    const data = new Uint8Array(300).map((_, i) => (i * 131 + 7) & 0xff);
    for (let n = 0; n <= 300; n++) {
      const bytes = data.subarray(0, n);
      const expected = createHash("sha256").update(bytes).digest("hex");
      expect(new Sha256().update(bytes).hex()).toBe(expected);
      const pieces = new Sha256();
      for (let i = 0; i < n; i += 1 + (i % 70)) pieces.update(bytes.subarray(i, Math.min(n, i + 1 + (i % 70))));
      expect(pieces.hex()).toBe(expected);
    }
  });

  it("takes no bytes after its digest", () => {
    const h = new Sha256();
    h.hex();
    expect(() => h.update(utf8("x"))).toThrow();
    expect(() => h.hex()).toThrow();
  });
});
