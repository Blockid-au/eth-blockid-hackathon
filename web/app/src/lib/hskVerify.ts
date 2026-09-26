import { createPublicClient, http, parseAbi } from "viem";
import { CHAINS } from "../wallet";

const H = CHAINS.hsk;
let client: ReturnType<typeof createPublicClient> | null = null;
function hskClient() {
  if (!client) {
    client = createPublicClient({
      chain: {
        id: H.id, name: H.name,
        nativeCurrency: { name: H.currency, symbol: H.currency, decimals: H.decimals },
        rpcUrls: { default: { http: [H.rpc] } },
      },
      transport: http(H.rpc, { timeout: 15000 }),
    });
  }
  return client;
}

const PROV_ABI = parseAbi(["function verify(uint256 id, bytes32 contentHash) view returns (bool)"]);

/** eth_call AgentProvenance.verify(id, contentHash) on HashKey Chain testnet. */
export async function verifyProposal(contract: string, id: number, contentHash: `0x${string}`): Promise<boolean> {
  const ok = await hskClient().readContract({
    address: contract as `0x${string}`,
    abi: PROV_ABI,
    functionName: "verify",
    args: [BigInt(id), contentHash],
  });
  return ok === true;
}
