import { createSiweMessage } from "viem/siwe";
import { generatePrivateKey, privateKeyToAccount, type PrivateKeyAccount } from "viem/accounts";
import { api, request, type Role } from "./api";
import { SIWE_DOMAIN, SIWE_URI } from "./wallet";

/**
 * Keys created in this browser, for people without MetaMask ("Try it now" and Google sign-in).
 *
 * - The secp256k1 private key is generated here (viem, crypto.getRandomValues) and never sent to the server.
 * - At rest it is encrypted with AES-256-GCM under a non-extractable WebCrypto key; both live in IndexedDB, so page
 *   script can use the key but cannot read the wrapping key's bytes.
 * - One slot per identity: "guest", or "google:<sub>". The first Google sign-in in a browser that already has a guest
 *   key reuses it, so a guest keeps what they did.
 * - Sign-in = a normal EIP-4361 (SIWE) message signed by this key, exactly like MetaMask.
 */

const DB = "blockid-wallet";
const STORE = "keys";

interface Stored {
  slot: string;
  address: string;
  iv: Uint8Array;
  ct: ArrayBuffer;
  wrap: CryptoKey;
  created: number;
}

function idb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = () => r.result.createObjectStore(STORE, { keyPath: "slot" });
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error ?? new Error("IndexedDB unavailable"));
  });
}

async function tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await idb();
  try {
    return await new Promise<T>((resolve, reject) => {
      const req = fn(db.transaction(STORE, mode).objectStore(STORE));
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  } finally {
    db.close();
  }
}

const hexToBytes = (h: string) => Uint8Array.from((h.replace(/^0x/, "").match(/../g) ?? []).map((b) => parseInt(b, 16)));
const bytesToHex = (b: ArrayBuffer) => "0x" + [...new Uint8Array(b)].map((x) => x.toString(16).padStart(2, "0")).join("");

async function save(slot: string, pk: `0x${string}`): Promise<PrivateKeyAccount> {
  const account = privateKeyToAccount(pk);
  const wrap = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, wrap, hexToBytes(pk));
  const rec: Stored = { slot, address: account.address, iv, ct, wrap, created: Date.now() };
  await tx("readwrite", (s) => s.put(rec));
  return account;
}

async function load(slot: string): Promise<{ account: PrivateKeyAccount; pk: `0x${string}` } | null> {
  const rec = (await tx("readonly", (s) => s.get(slot))) as Stored | undefined;
  if (!rec) return null;
  const raw = await crypto.subtle.decrypt({ name: "AES-GCM", iv: rec.iv }, rec.wrap, rec.ct);
  const pk = bytesToHex(raw) as `0x${string}`;
  return { account: privateKeyToAccount(pk), pk };
}

/** The key for a slot, created on first use. */
async function ensure(slot: string, adoptGuest = false): Promise<PrivateKeyAccount> {
  const have = await load(slot);
  if (have) return have.account;
  if (adoptGuest) {
    const guest = await load("guest");
    if (guest) return save(slot, guest.pk);
  }
  return save(slot, generatePrivateKey());
}

/** `sub` claim of a Google ID token (only to pick the local slot; the server verifies the token). */
export function googleSub(credential: string): string {
  try {
    const p = credential.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    return String(JSON.parse(atob(p + "===".slice((p.length + 3) % 4))).sub || "");
  } catch {
    return "";
  }
}

async function siweFor(account: PrivateKeyAccount): Promise<{ message: string; signature: string }> {
  const { nonce } = await api.nonce();
  const message = createSiweMessage({
    domain: SIWE_DOMAIN,
    address: account.address,
    statement: "Sign in to BlockID Business Passport.",
    uri: SIWE_URI,
    version: "1",
    chainId: 262626,
    nonce,
    issuedAt: new Date(),
    expirationTime: new Date(Date.now() + 10 * 60 * 1000),
  });
  return { message, signature: await account.signMessage({ message }) };
}

const LAST = "blockid-device-slot";

export async function signInWithDeviceKey(
  opts: { method: "guest" } | { method: "google"; credential: string },
): Promise<{ address: string; role: Role }> {
  if (opts.method === "guest") {
    const account = await ensure("guest");
    const { message, signature } = await siweFor(account);
    const r = await request<{ address: string; role: Role }>("POST", "/v1/auth/siwe", { message, signature, method: "guest" });
    remember("guest");
    return r;
  }
  const sub = googleSub(opts.credential);
  if (!sub) throw new Error("Google sign-in failed. Please try again.");
  const slot = "google:" + sub;
  const account = await ensure(slot, true);
  const { message, signature } = await siweFor(account);
  const lang = (() => { try { return localStorage.getItem("blockid-lang") === "vi" ? "vi" : "en"; } catch { return "en"; } })();
  const r = await request<{ address: string; role: Role }>("POST", "/v1/auth/google", { credential: opts.credential, message, signature, lang });
  remember(slot);
  return r;
}

function remember(slot: string) {
  try { localStorage.setItem(LAST, slot); } catch { /* private mode */ }
}

/** Slot that holds the key for this address, if any (for backup/export). */
export async function slotFor(address: string): Promise<string | null> {
  const all = (await tx("readonly", (s) => s.getAll())) as Stored[];
  return all.find((r) => r.address.toLowerCase() === address.toLowerCase())?.slot ?? null;
}

/** Private key for backup. Only called from an explicit "Show my key" action. */
export async function exportKey(address: string): Promise<string | null> {
  const slot = await slotFor(address);
  if (!slot) return null;
  return (await load(slot))?.pk ?? null;
}

/** Restore a backed-up key into the guest slot and sign in with it. */
export async function importKey(pk: string): Promise<{ address: string; role: Role }> {
  const clean = pk.trim().toLowerCase().replace(/^(0x)?/, "0x");
  if (!/^0x[0-9a-f]{64}$/.test(clean)) throw new Error("This is not a valid private key (64 hex characters).");
  await save("guest", clean as `0x${string}`);
  return signInWithDeviceKey({ method: "guest" });
}

export async function hasDeviceKey(address: string): Promise<boolean> {
  try { return (await slotFor(address)) !== null; } catch { return false; }
}
