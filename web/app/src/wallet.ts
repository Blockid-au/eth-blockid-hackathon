import { getAddress, toHex } from "viem";
import { createSiweMessage } from "viem/siwe";
import { api, isMock, type Role } from "./api";

/** EIP-4361 domain: eth.blockid.au in production; the backend also accepts localhost for local dev. */
const LOCAL = typeof location !== "undefined" && /^(localhost|127\.0\.0\.1)$/.test(location.hostname);
export const SIWE_DOMAIN = LOCAL ? location.host : "eth.blockid.au";
export const SIWE_URI = LOCAL ? `${location.protocol}//${location.host}` : "https://eth.blockid.au";

export interface ChainInfo {
  key: "local" | "hoodi";
  id: number;
  hex: string;
  name: string;
  rpc: string;
  currency: string;
  decimals: number;
  explorer: string;
  tokenUrl: (a: string) => string;
  txUrl: (h: string) => string;
  addrUrl: (a: string) => string;
}

export const CHAINS: Record<"local" | "hoodi", ChainInfo> = {
  local: {
    key: "local",
    id: 262626,
    hex: "0x401e2",
    name: "BlockID Chain",
    rpc: "https://eth.blockid.au/rpc",
    currency: "BLKD",
    decimals: 18,
    explorer: "https://scan.blockid.au",
    tokenUrl: (a) => `https://scan.blockid.au/token/${a}`,
    txUrl: (h) => `https://scan.blockid.au/tx/${h}`,
    addrUrl: (a) => `https://scan.blockid.au/address/${a}`,
  },
  hoodi: {
    key: "hoodi",
    id: 560048,
    hex: "0x88bb0",
    name: "Ethereum Hoodi",
    rpc: "https://ethereum-hoodi-rpc.publicnode.com",
    currency: "ETH",
    decimals: 18,
    explorer: "https://hoodi.etherscan.io",
    tokenUrl: (a) => `https://hoodi.etherscan.io/token/${a}`,
    txUrl: (h) => `https://hoodi.etherscan.io/tx/${h}`,
    addrUrl: (a) => `https://hoodi.etherscan.io/address/${a}`,
  },
};

/** Map an events.chain value (\"local\", \"hoodi\", 262626, \"560048\", …) to a chain. */
export function chainOf(c: unknown): ChainInfo {
  const s = String(c ?? "").toLowerCase();
  if (s.includes("hoodi") || s === "560048" || s === "0x88bb0") return CHAINS.hoodi;
  return CHAINS.local;
}

interface Eip1193 {
  request: (args: { method: string; params?: unknown[] | Record<string, unknown> }) => Promise<unknown>;
}
declare global {
  interface Window {
    ethereum?: Eip1193;
  }
}

export class WalletError extends Error {
  code: "nomm" | "rejected" | "other";
  constructor(code: WalletError["code"], msg?: string) {
    super(msg || code);
    this.name = "WalletError";
    this.code = code;
  }
}

function provider(): Eip1193 {
  if (!window.ethereum) throw new WalletError("nomm");
  return window.ethereum;
}

function wrap(e: unknown): never {
  if (e instanceof WalletError) throw e;
  const err = e as { code?: number; message?: string };
  if (err?.code === 4001) throw new WalletError("rejected", err.message);
  throw new WalletError("other", err?.message || String(e));
}

export function isAddressValid(a: string): string | null {
  try {
    return getAddress(a.trim());
  } catch {
    return null;
  }
}

export { shortAddr } from "./lib/addr";

/** SIWE: nonce → EIP-4361 message → personal_sign → POST /auth/siwe. */
export async function signInWithEthereum(): Promise<{ address: string; role: Role }> {
  if (isMock && !window.ethereum) {
    const { nonce } = await api.nonce();
    return api.siwe(`mock sign-in ${nonce}`, "0xmock");
  }
  const eth = provider();
  try {
    const accounts = (await eth.request({ method: "eth_requestAccounts" })) as string[];
    if (!accounts?.length) throw new WalletError("other", "No account");
    const address = getAddress(accounts[0]);
    let chainId = 262626;
    try {
      const hex = (await eth.request({ method: "eth_chainId" })) as string;
      const id = parseInt(hex, 16);
      if (id === 262626 || id === 560048) chainId = id;
    } catch {
      /* default */
    }
    const { nonce } = await api.nonce();
    const message = createSiweMessage({
      domain: SIWE_DOMAIN,
      address,
      statement: "Sign in to BlockID Issuance Studio.",
      uri: SIWE_URI,
      version: "1",
      chainId,
      nonce,
      issuedAt: new Date(),
      expirationTime: new Date(Date.now() + 10 * 60 * 1000),
    });
    const signature = (await eth.request({ method: "personal_sign", params: [toHex(message), address] })) as string;
    return await api.siwe(message, signature);
  } catch (e) {
    if (e instanceof Error && "status" in e) throw e; // ApiError
    wrap(e);
  }
}

export async function switchOrAddChain(c: ChainInfo): Promise<void> {
  const eth = provider();
  try {
    await eth.request({ method: "wallet_switchEthereumChain", params: [{ chainId: c.hex }] });
  } catch (e) {
    const err = e as { code?: number; data?: { originalError?: { code?: number } } };
    const code = err?.code ?? err?.data?.originalError?.code;
    if (code === 4902 || code === -32603) {
      try {
        await eth.request({
          method: "wallet_addEthereumChain",
          params: [
            {
              chainId: c.hex,
              chainName: c.name,
              nativeCurrency: { name: c.currency, symbol: c.currency, decimals: c.decimals },
              rpcUrls: [c.rpc],
              blockExplorerUrls: [c.explorer],
            },
          ],
        });
      } catch (e2) {
        wrap(e2);
      }
    } else {
      wrap(e);
    }
  }
}

/** Switch/add the chain, then wallet_watchAsset {address, symbol: ticker, decimals: 0}. */
export async function addTokenToWallet(c: ChainInfo, address: string, symbol: string): Promise<boolean> {
  await switchOrAddChain(c);
  try {
    const ok = await provider().request({
      method: "wallet_watchAsset",
      params: { type: "ERC20", options: { address: getAddress(address), symbol, decimals: 0 } },
    });
    return ok !== false;
  } catch (e) {
    wrap(e);
  }
}
