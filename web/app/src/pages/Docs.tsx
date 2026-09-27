import { Link } from "react-router-dom";
import { useI18n } from "../i18n";
import { useTitle } from "../lib/hooks";
import "./docs.css";

/**
 * /docs — how the platform is built (layers: people → app & services → Layer 1 BlockID EVM → Layer 2 HashKey Chain
 * + Ethereum anchor) and the full feature list. Self-contained EN/VI copy; facts follow docs/FACTS.md.
 */

const REPO = "https://github.com/Blockid-au/eth-blockid-hackathon/blob/main";

type Node = { t: string; s: string; c?: "gold" | "red" | "blue" };
type Copy = {
  eyebrow: string; title: string; msg: string;
  toc: [string, string][];
  arch: { h: string; lede: string; people: [string, string]; app: [string, string]; one: [string, string, string]; two: [string, string, string];
    nPeople: Node[]; nApp: Node[]; nOne: Node[]; nTwo: Node[]; eth: Node;
    l1: string[]; l2: string[]; proofH: string; proof: string[] };
  flowH: string; flowLede: string; flow: { t: string; s: string; gate?: boolean }[];
  featH: string; featLede: string; feat: { h: string; items: [string, string][] }[];
  chainH: string; chainCols: string[]; chains: [string, string, string, string, string][];
  contracts: string;
  docsH: string; docs: [string, string, string][];
  legal: string;
};

const en: Copy = {
  eyebrow: "Docs",
  title: "How BlockID Business Passport is built",
  msg: "One web app, services that never hold keys, a person who approves every step, and two blockchain layers that anyone can check.",
  toc: [["arch", "Architecture"], ["flow", "How the layers talk"], ["features", "All features"], ["chains", "Chains & contracts"], ["more", "More docs"]],
  arch: {
    h: "Architecture",
    lede: "Four layers. Only an action a person approved can reach a blockchain, and only the isolated issuer can sign it.",
    people: ["People", "who uses it"], app: ["App & services", "off-chain"],
    one: ["Layer 1", "BlockID EVM · 262626", "BlockID Chain: the share register of record · gas price 0"],
    two: ["Layer 2", "HashKey Chain · 133", "HashKey Chain: public proof for real-world assets"],
    nPeople: [
      { t: "Investors", s: "portfolio, updates, dividends, checks" },
      { t: "Businesses", s: "evaluate, list, shareholders, updates" },
      { t: "Approvers", s: "a person signs every chain action", c: "gold" },
    ],
    nApp: [
      { t: "Web app", s: "eth.blockid.au · EN/VI · Google sign-in, browser key or MetaMask", c: "blue" },
      { t: "Analysis", s: "reads public sources, fixed formula sets the value · no keys", c: "blue" },
      { t: "Approval queue", s: "admin wallet signs one approval per step · audit log", c: "gold" },
      { t: "Issuer", s: "the only key holder · isolated network · acts on approved rows only", c: "red" },
    ],
    nOne: [
      { t: "Identity registry", s: "KYC-verified holders only" },
      { t: "Share token", s: "1 token = 1 share · pause, forced transfer" },
      { t: "Dividend distributor", s: "paid in mAUD · relayer pays gas" },
      { t: "Report hash", s: "fair-value report fingerprint" },
    ],
    nTwo: [
      { t: "Mirror share token", s: "same balances, paused" },
      { t: "CapTableAnchor", s: "Merkle root of the cap table" },
      { t: "AgentProvenance", s: "who proposed, who approved" },
    ],
    eth: { t: "Ethereum (Hoodi)", s: "public anchor · mirror token + cap-table root · chain 560048", c: "blue" },
    l1: ["issuer signs", "register · KYC · issue · dividends · report hash"],
    l2: ["issuer syncs", "same balances + Merkle root + report hash"],
    proofH: "Anyone checks",
    proof: ["/verify recomputes the report hash in your browser and reads it from all three chains.", "Match ✓ · any change ✗", "Explorers: scan.blockid.au · HashKey explorer · Etherscan"],
  },
  flowH: "How the layers talk",
  flowLede: "The same path for every business. Steps marked ◆ wait for a person.",
  flow: [
    { t: "The business pastes its website", s: "The link is checked first; figures the business adds are labelled as its own." },
    { t: "Analysis builds a fair-value report", s: "Reads up to 6 pages and a few web searches. Every number keeps its source; a fixed formula gives the business score (A–E) and a value range. No keys." },
    { t: "◆ A person approves the value", s: "An admin can adjust any score before approving.", gate: true },
    { t: "The business sets its share code and shareholders", s: "Default price A$1.00 per share: shares = approved value ÷ 1." },
    { t: "◆ One listing approval", s: "An admin wallet signs one approval for the whole listing.", gate: true },
    { t: "Layer 1: the issuer records the shares on BlockID Chain", s: "Registry, KYC for each holder, share token, dividend distributor, report hash. Gas price 0." },
    { t: "Layer 2: the issuer copies the proof to HashKey Chain and Ethereum", s: "A paused mirror token with the same balances and a Merkle root of the cap table. A failed chain can be re-synced." },
    { t: "Investors hold, follow and check", s: "Shares appear in their wallet; approved updates and dividends reach every investor at the same time; /verify checks the records." },
  ],
  featH: "All features",
  featLede: "Everything that is live on the testnet today.",
  feat: [
    { h: "For investors", items: [
      ["My portfolio", "every business you own, value at the latest approved price, dividends received"],
      ["Demo account", "opens on the first visit, no sign-up; use your own wallet any time"],
      ["Sign in with Google", "a key is created in your browser and linked to your Google account; it never leaves the browser"],
      ["Business updates", "weekly to yearly updates in plain language, approved by a person, same time for everyone"],
      ["Dividends to your wallet", "paid automatically in test Australian dollars; no gas fees for holders"],
      ["Share offerings (simulated)", "read the information pack, reserve shares, withdraw before it closes"],
      ["Add to wallet", "one click adds the share token and network to MetaMask on all three chains"],
      ["Check the records", "recompute any report hash in your browser, no login"],
    ] },
    { h: "For businesses", items: [
      ["Evaluate a business", "paste a website, optional revenue figures; research runs in minutes with live progress"],
      ["Fair-value report", "business score A–E, value range, competitors, market and every source cited"],
      ["Share code and shareholders", "3-letter code, names, wallets and percentages"],
      ["List on blockchain", "one approval creates the register on BlockID Chain and copies it to HashKey Chain and Ethereum"],
      ["Updates", "enter the numbers, check the draft, send for approval, published to every investor"],
      ["Share offering (simulated)", "open an offering with an information pack; an admin approves opening and settlement"],
      ["Dividend rule", "approved once; after each update there are 24 hours to cancel, then every wallet is paid"],
      ["Transfers", "free (holder signs) or approval mode (issuer moves shares after an admin approves), KYC requests"],
      ["New shares and revaluations", "dilution preview before minting; value per share = valuation ÷ shares"],
      ["Workspace", "overview chart, cap table, activity, team roles"],
    ] },
    { h: "For approvers (admin)", items: [
      ["Inbox and queues", "valuations, listings, sync, new shares, dividends, dividend rules, updates, offerings — in flow order"],
      ["One item per screen", "approve or reject with your own wallet; returns you to the founder's next step"],
      ["Dashboard", "live platform numbers, companies, activity"],
      ["Issuer wallets and re-sync", "balances on every chain; re-sync only the chain that failed"],
      ["Audit log", "every decision and chain action, hash-chained"],
    ] },
    { h: "Trust and security", items: [
      ["No keys in analysis", "a fixed permission table blocks signing, sending, deploying and shell for every agent"],
      ["Isolated issuer", "the only key holder, on its own network; acts only on approved rows"],
      ["Two-layer proof", "BlockID Chain is the record; HashKey Chain and Ethereum hold the public proof"],
      ["Safe crawler", "public IPs only, per-hop redirect checks, size and time limits"],
      ["Web hardening", "Cloudflare, strict content-security policy, sign-in with wallet signatures"],
      ["Testnet only", "not an offer of securities or financial advice"],
    ] },
  ],
  chainH: "Chains & contracts",
  chainCols: ["Chain", "Chain id", "Role", "Explorer"],
  chains: [
    ["BlockID Chain (Cosmos EVM)", "262626", "Layer 1 · share register of record, gas 0", "scan.blockid.au", "https://scan.blockid.au"],
    ["HashKey Chain testnet", "133", "Layer 2 · RWA proof: mirror token, CapTableAnchor, AgentProvenance", "testnet-explorer.hskchain.net", "https://testnet-explorer.hskchain.net"],
    ["Ethereum Hoodi testnet", "560048", "Public anchor: mirror token + CapTableAnchor", "hoodi.etherscan.io", "https://hoodi.etherscan.io"],
  ],
  contracts: "Platform contracts",
  docsH: "More docs",
  docs: [
    ["Architecture", "system context, deployment, security", `${REPO}/docs/ARCHITECTURE.md`],
    ["Architecture diagrams", "12 diagrams: pipeline, issuance, verify, contracts", `${REPO}/docs/ARCHITECTURE-DIAGRAMS.md`],
    ["Feature gallery", "every screen with a screenshot", `${REPO}/docs/FEATURES.md`],
    ["User guide", "step by step for investors and businesses", `${REPO}/docs/USER-GUIDE.md`],
    ["Security", "trust boundaries and threat model", `${REPO}/docs/SECURITY.md`],
    ["Pitch deck (3 min)", "PDF", "/deck/BlockID-Business-Passport-3min.pdf"],
  ],
  legal: "Testnet demo. Not an offer of securities or financial advice.",
};

const vi: Copy = {
  ...en,
  eyebrow: "Tài liệu",
  title: "BlockID Business Passport được xây dựng thế nào",
  msg: "Một ứng dụng web, các dịch vụ không bao giờ giữ khóa, một người phê duyệt mọi bước, và hai tầng blockchain mà ai cũng kiểm tra được.",
  toc: [["arch", "Kiến trúc"], ["flow", "Các tầng giao tiếp"], ["features", "Toàn bộ tính năng"], ["chains", "Chain & hợp đồng"], ["more", "Tài liệu khác"]],
  arch: {
    ...en.arch,
    h: "Kiến trúc",
    lede: "Bốn tầng. Chỉ hành động đã được một người phê duyệt mới đến được blockchain, và chỉ issuer tách biệt mới ký được.",
    people: ["Người dùng", "ai sử dụng"], app: ["Ứng dụng & dịch vụ", "ngoài chuỗi"],
    one: ["Layer 1", "BlockID EVM · 262626", "BlockID Chain: sổ cổ đông gốc · phí gas 0"],
    two: ["Layer 2", "HashKey Chain · 133", "HashKey Chain: bằng chứng công khai cho tài sản thực"],
    nPeople: [
      { t: "Nhà đầu tư", s: "danh mục, cập nhật, cổ tức, kiểm tra" },
      { t: "Doanh nghiệp", s: "định giá, niêm yết, cổ đông, cập nhật" },
      { t: "Người phê duyệt", s: "một người ký mọi hành động trên chuỗi", c: "gold" },
    ],
    nApp: [
      { t: "Ứng dụng web", s: "eth.blockid.au · EN/VI · Google, khóa trình duyệt hoặc MetaMask", c: "blue" },
      { t: "Phân tích", s: "đọc nguồn công khai, công thức cố định ra giá trị · không giữ khóa", c: "blue" },
      { t: "Hàng chờ phê duyệt", s: "ví admin ký một lần mỗi bước · nhật ký kiểm toán", c: "gold" },
      { t: "Issuer", s: "nơi duy nhất giữ khóa · mạng tách biệt · chỉ làm việc đã duyệt", c: "red" },
    ],
    nOne: [
      { t: "Identity registry", s: "chỉ cổ đông đã KYC" },
      { t: "Share token", s: "1 token = 1 cổ phần · tạm dừng, chuyển cưỡng chế" },
      { t: "Dividend distributor", s: "trả bằng mAUD · relayer trả gas" },
      { t: "Report hash", s: "dấu vân tay của báo cáo định giá" },
    ],
    nTwo: [
      { t: "Mirror share token", s: "cùng số dư, đang tạm dừng" },
      { t: "CapTableAnchor", s: "Merkle root của sổ cổ đông" },
      { t: "AgentProvenance", s: "ai đề xuất, ai phê duyệt" },
    ],
    eth: { t: "Ethereum (Hoodi)", s: "neo công khai · mirror token + root sổ cổ đông · chain 560048", c: "blue" },
    l1: ["issuer ký", "sổ cổ đông · KYC · phát hành · cổ tức · report hash"],
    l2: ["issuer đồng bộ", "cùng số dư + Merkle root + report hash"],
    proofH: "Ai cũng kiểm tra được",
    proof: ["/verify tính lại hash báo cáo ngay trong trình duyệt và đọc hash trên cả ba chain.", "Khớp ✓ · sửa bất kỳ ✗", "Explorer: scan.blockid.au · HashKey explorer · Etherscan"],
  },
  flowH: "Các tầng giao tiếp với nhau thế nào",
  flowLede: "Cùng một quy trình cho mọi doanh nghiệp. Bước có ◆ chờ một người phê duyệt.",
  flow: [
    { t: "Doanh nghiệp dán website", s: "Đường link được kiểm tra trước; số liệu doanh nghiệp tự nhập được ghi rõ là tự khai." },
    { t: "Phân tích lập báo cáo giá trị hợp lý", s: "Đọc tối đa 6 trang và vài lượt tìm kiếm. Mỗi con số giữ nguồn; công thức cố định cho điểm doanh nghiệp (A–E) và khoảng giá trị. Không giữ khóa." },
    { t: "◆ Một người phê duyệt giá trị", s: "Admin có thể chỉnh bất kỳ điểm nào trước khi duyệt.", gate: true },
    { t: "Doanh nghiệp đặt mã cổ phần và cổ đông", s: "Giá mặc định A$1.00/cổ phần: số cổ phần = giá trị đã duyệt ÷ 1." },
    { t: "◆ Một lần duyệt niêm yết", s: "Ví admin ký một lần cho toàn bộ việc niêm yết.", gate: true },
    { t: "Layer 1: issuer ghi cổ phần lên BlockID Chain", s: "Registry, KYC từng cổ đông, share token, dividend distributor, report hash. Phí gas 0." },
    { t: "Layer 2: issuer sao chép bằng chứng sang HashKey Chain và Ethereum", s: "Mirror token tạm dừng với cùng số dư và Merkle root của sổ cổ đông. Chain lỗi có thể đồng bộ lại." },
    { t: "Nhà đầu tư nắm giữ, theo dõi và kiểm tra", s: "Cổ phần hiện trong ví; cập nhật đã duyệt và cổ tức đến mọi nhà đầu tư cùng lúc; /verify kiểm tra hồ sơ." },
  ],
  featH: "Toàn bộ tính năng",
  featLede: "Mọi thứ đang chạy trên testnet hôm nay.",
  feat: [
    { h: "Cho nhà đầu tư", items: [
      ["Danh mục của tôi", "mọi doanh nghiệp bạn sở hữu, giá trị theo giá đã duyệt gần nhất, cổ tức đã nhận"],
      ["Tài khoản demo", "tự mở ở lần truy cập đầu, không cần đăng ký; dùng ví riêng bất cứ lúc nào"],
      ["Đăng nhập Google", "khóa được tạo trong trình duyệt và gắn với tài khoản Google; không rời khỏi trình duyệt"],
      ["Cập nhật doanh nghiệp", "từ hằng tuần đến hằng năm, lời lẽ đơn giản, được một người duyệt, mọi người nhận cùng lúc"],
      ["Cổ tức vào ví", "trả tự động bằng đô la Úc thử nghiệm; cổ đông không trả phí gas"],
      ["Đợt chào bán cổ phần (mô phỏng)", "đọc bộ thông tin, đặt mua cổ phần, rút lại trước khi đóng"],
      ["Thêm vào ví", "một cú bấm thêm token và mạng vào MetaMask trên cả ba chain"],
      ["Kiểm tra hồ sơ", "tính lại hash báo cáo ngay trong trình duyệt, không cần đăng nhập"],
    ] },
    { h: "Cho doanh nghiệp", items: [
      ["Đánh giá doanh nghiệp", "dán website, có thể nhập doanh thu; phân tích chạy trong vài phút, xem tiến độ trực tiếp"],
      ["Báo cáo giá trị hợp lý", "điểm A–E, khoảng giá trị, đối thủ, thị trường và nguồn của mọi con số"],
      ["Mã cổ phần và cổ đông", "mã 3 chữ, tên, ví và tỷ lệ"],
      ["Niêm yết trên blockchain", "một lần duyệt tạo sổ cổ đông trên BlockID Chain và sao chép sang HashKey Chain, Ethereum"],
      ["Cập nhật", "nhập số liệu, xem bản nháp, gửi duyệt, phát hành cho mọi nhà đầu tư"],
      ["Chào bán cổ phần (mô phỏng)", "mở đợt chào bán kèm bộ thông tin; admin duyệt mở và tất toán"],
      ["Quy tắc cổ tức", "duyệt một lần; sau mỗi cập nhật có 24 giờ để hủy, rồi trả vào mọi ví"],
      ["Chuyển nhượng", "tự do (cổ đông ký) hoặc cần duyệt (issuer chuyển sau khi admin duyệt), yêu cầu KYC"],
      ["Phát hành thêm và định giá lại", "xem trước mức pha loãng; giá mỗi cổ phần = định giá ÷ số cổ phần"],
      ["Không gian làm việc", "biểu đồ tổng quan, sổ cổ đông, hoạt động, vai trò nhóm"],
    ] },
    { h: "Cho người phê duyệt (admin)", items: [
      ["Hộp thư và hàng chờ", "định giá, niêm yết, đồng bộ, phát hành thêm, cổ tức, quy tắc cổ tức, cập nhật, chào bán — theo thứ tự quy trình"],
      ["Mỗi việc một màn hình", "duyệt hoặc từ chối bằng ví của bạn; quay lại đúng bước tiếp theo của doanh nghiệp"],
      ["Bảng điều khiển", "số liệu nền tảng trực tiếp, doanh nghiệp, hoạt động"],
      ["Ví issuer và đồng bộ lại", "số dư trên mọi chain; chỉ đồng bộ lại chain bị lỗi"],
      ["Nhật ký kiểm toán", "mọi quyết định và hành động trên chuỗi, nối chuỗi hash"],
    ] },
    { h: "Tin cậy và bảo mật", items: [
      ["Phân tích không giữ khóa", "bảng quyền cố định chặn ký, gửi, deploy và shell cho mọi agent"],
      ["Issuer tách biệt", "nơi duy nhất giữ khóa, mạng riêng; chỉ làm việc đã được duyệt"],
      ["Bằng chứng hai tầng", "BlockID Chain là sổ gốc; HashKey Chain và Ethereum giữ bằng chứng công khai"],
      ["Crawler an toàn", "chỉ IP công khai, kiểm tra từng lần chuyển hướng, giới hạn dung lượng và thời gian"],
      ["Bảo vệ web", "Cloudflare, content-security policy chặt, đăng nhập bằng chữ ký ví"],
      ["Chỉ testnet", "không phải chào bán chứng khoán hay tư vấn tài chính"],
    ] },
  ],
  chainH: "Chain & hợp đồng",
  chainCols: ["Chain", "Chain id", "Vai trò", "Explorer"],
  chains: [
    ["BlockID Chain (Cosmos EVM)", "262626", "Layer 1 · sổ cổ đông gốc, gas 0", "scan.blockid.au", "https://scan.blockid.au"],
    ["HashKey Chain testnet", "133", "Layer 2 · bằng chứng RWA: mirror token, CapTableAnchor, AgentProvenance", "testnet-explorer.hskchain.net", "https://testnet-explorer.hskchain.net"],
    ["Ethereum Hoodi testnet", "560048", "Neo công khai: mirror token + CapTableAnchor", "hoodi.etherscan.io", "https://hoodi.etherscan.io"],
  ],
  contracts: "Hợp đồng nền tảng",
  docsH: "Tài liệu khác",
  docs: [
    ["Kiến trúc", "bối cảnh hệ thống, triển khai, bảo mật", `${REPO}/docs/ARCHITECTURE.md`],
    ["Sơ đồ kiến trúc", "12 sơ đồ: pipeline, phát hành, kiểm tra, hợp đồng", `${REPO}/docs/ARCHITECTURE-DIAGRAMS.md`],
    ["Thư viện tính năng", "mọi màn hình kèm ảnh chụp", `${REPO}/docs/FEATURES.md`],
    ["Hướng dẫn sử dụng", "từng bước cho nhà đầu tư và doanh nghiệp", `${REPO}/docs/USER-GUIDE.md`],
    ["Bảo mật", "ranh giới tin cậy và mô hình đe dọa", `${REPO}/docs/SECURITY.md`],
    ["Pitch deck (3 phút)", "PDF", "/deck/BlockID-Business-Passport-3min.pdf"],
  ],
  legal: "Bản demo trên testnet. Không phải chào bán chứng khoán hay tư vấn tài chính.",
};

const CONTRACTS: [string, string, string][] = [
  ["CapTableAnchor", "HashKey", "0x728c834DE493DC3e9Ae2f7C0e79d86701B6F9F04"],
  ["AgentProvenance", "HashKey", "0x6B96bcE8937e1416Ec1DAC4ADAdD71FE879F8e84"],
  ["CapTableAnchor", "Ethereum Hoodi", "0xF3dC95D5d207dE9f2aC98184Fd32b45B72334263"],
  ["DemoAUD (mAUD)", "BlockID Chain", "0x286C1eD22A741F4939A3C7637011B0fAE2C7FFBc"],
];

function Nodes({ list }: { list: Node[] }) {
  return (
    <div className="nodes">
      {list.map((n) => (
        <div key={n.t} className={"node" + (n.c ? ` n-${n.c}` : "")}><b>{n.t}</b><span>{n.s}</span></div>
      ))}
    </div>
  );
}

function Lab({ t, s }: { t: string; s: string }) {
  return <div className="layer-lab"><b>{t}</b><span>{s}</span></div>;
}

export default function DocsPage() {
  const { lang } = useI18n();
  const c = lang === "vi" ? vi : en;
  const a = c.arch;
  useTitle(c.eyebrow);
  return (
    <div className="wrap page docs">
      <div className="head">
        <span className="eyebrow">{c.eyebrow}</span>
        <h2>{c.title}</h2>
        <p>{c.msg}</p>
      </div>
      <nav className="toc" aria-label={c.eyebrow}>
        {c.toc.map(([id, label]) => <a key={id} className="chip" href={`#${id}`}>{label}</a>)}
      </nav>

      <section id="arch" style={{ marginTop: 28 }}>
        <h3>{a.h}</h3>
        <p className="lede">{a.lede}</p>
        <div className="arch">
          <div className="arch-stack">
            <div className="layer l-people"><Lab t={a.people[0]} s={a.people[1]} /><div className="layer-body bare"><Nodes list={a.nPeople} /></div></div>
            <div className="link-row l-people"><div /><div><i>↕</i> HTTPS · Google / wallet sign-in</div></div>
            <div className="layer l-app"><Lab t={a.app[0]} s={a.app[1]} /><div className="layer-body bare"><Nodes list={a.nApp} /></div></div>
            <div className="link-row l-one"><div /><div><i>↓ {a.l1[0]}</i> {a.l1[1]}</div></div>
            <div className="layer l-one">
              <Lab t={a.one[0]} s={a.one[1]} />
              <div className="layer-body"><span className="layer-title">{a.one[2]}</span><Nodes list={a.nOne} /></div>
            </div>
            <div className="link-row l-two"><div /><div><i>↓ {a.l2[0]}</i> {a.l2[1]}</div></div>
            <div className="layer l-two">
              <Lab t={a.two[0]} s={a.two[1]} />
              <div className="layer-body">
                <span className="layer-title">{a.two[2]}</span>
                <Nodes list={a.nTwo} />
                <Nodes list={[a.eth]} />
              </div>
            </div>
          </div>
          <aside className="proof">
            <b>{a.proofH}</b>
            {a.proof.map((p) => <p key={p}>{p}</p>)}
            <Link className="btn sm" to="/verify">/verify →</Link>
            <Link to="/hsk">HashKey Chain →</Link>
          </aside>
        </div>
      </section>

      <section id="flow">
        <h3>{c.flowH}</h3>
        <p className="lede">{c.flowLede}</p>
        <ol className="flow">
          {c.flow.map((f) => <li key={f.t}><div><b className={f.gate ? "gate" : undefined}>{f.t}</b><span>{f.s}</span></div></li>)}
        </ol>
      </section>

      <section id="features">
        <h3>{c.featH}</h3>
        <p className="lede">{c.featLede}</p>
        <div className="fgrid">
          {c.feat.map((g) => (
            <div key={g.h} className="card solid">
              <h4>{g.h}</h4>
              <ul>{g.items.map(([t, s]) => <li key={t}><b>{t}</b> <span>— {s}</span></li>)}</ul>
            </div>
          ))}
        </div>
      </section>

      <section id="chains">
        <h3>{c.chainH}</h3>
        <div className="card solid" style={{ gap: 0 }}>
          <div className="chain-row h">{c.chainCols.map((h) => <span key={h}>{h}</span>)}</div>
          {c.chains.map(([n, id, role, ex, url]) => (
            <div key={id} className="chain-row"><b>{n}</b><code>{id}</code><span>{role}</span><a href={url} target="_blank" rel="noopener noreferrer">{ex} →</a></div>
          ))}
        </div>
        <div className="card solid" style={{ gap: 0 }}>
          <h4 style={{ marginBottom: 6 }}>{c.contracts}</h4>
          {CONTRACTS.map(([n, ch, addr]) => (
            <div key={addr} className="chain-row"><b>{n}</b><span>{ch}</span><code>{addr}</code><span /></div>
          ))}
        </div>
      </section>

      <section id="more">
        <h3>{c.docsH}</h3>
        <div className="docs-links">
          {c.docs.map(([t, s, href]) => (
            <a key={t} href={href} target={href.startsWith("http") ? "_blank" : undefined} rel="noopener noreferrer"><b>{t}</b><span>{s}</span></a>
          ))}
        </div>
        <p className="muted-sm">{c.legal}</p>
      </section>
    </div>
  );
}
