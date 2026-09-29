/**
 * Terms of Use and Privacy Policy text (EN + VI), shown at /terms and /privacy on eth.blockid.au and hr.blockid.au.
 *
 * Facts come from docs/COMPANY.md, docs/FACTS.md, docs/SECURITY.md, docs/ARCHITECTURE.md, docs/LLM-ROUTING.md,
 * docs/PLAN-GTM.md and docs/PLAN-BUSINESS.md. Where something is not decided yet the text says so. Keep EN and VI in
 * step (the VI type is the EN type). Pending review by a lawyer (docs/COMPANY.md §6 item 7).
 *
 * Inline markup understood by the renderer (Legal.tsx): **bold**, emails, https:// links and the paths /terms,
 * /privacy (router links). A block is a paragraph (string) or a bullet list (string[]).
 */

export type Block = string | string[];
export interface Section { id: string; h: string; body: Block[] }
export interface LegalDoc { eyebrow: string; title: string; lede: string; sections: Section[] }
export interface LegalCopy {
  updated: string;
  review: string;
  toc: string;
  other: { terms: string; privacy: string };
  contactH: string;
  contact: string;
  terms: LegalDoc;
  privacy: LegalDoc;
}

export const LEGAL_UPDATED_ISO = "2026-09-29";
export const CONTACT_EMAIL = "admin@blockid.au";

export const legalEn: LegalCopy = {
  updated: "Last updated 29 September 2026",
  review: "This version is pending legal review. It describes how the service works today and may change after that review.",
  toc: "On this page",
  other: { terms: "Terms of Use", privacy: "Privacy Policy" },
  contactH: "Questions?",
  contact: "Write to admin@blockid.au. Auschain Pty Ltd · ABN 79 659 615 111 · ACN 659 615 111 · New South Wales, Australia.",

  terms: {
    eyebrow: "Legal",
    title: "Terms of Use",
    lede: "The rules for using BlockID Business Passport (eth.blockid.au), BlockID HR (hr.blockid.au) and the BlockID explorer (scan.blockid.au). Please read them together with our Privacy Policy.",
    sections: [
      {
        id: "who",
        h: "1. Who we are",
        body: [
          "The BlockID services are operated by **Auschain Pty Ltd** (ABN 79 659 615 111, ACN 659 615 111), an Australian private company (\"we\", \"us\"). BlockID™ is a trade mark of Auschain Pty Ltd. It is not a registered trade mark.",
          "By using the services you agree to these terms. If you do not agree, please do not use the services.",
        ],
      },
      {
        id: "pilot",
        h: "2. A free pilot on test networks",
        body: [
          "The services are a pilot and demonstration. They are currently **free**: we do not take any payment. If we introduce paid plans later, we will tell you first and publish updated terms. We will not charge you without your agreement.",
          "Because this is a pilot, features can change, stop working or be removed, and data on the test networks can be reset. Please do not rely on the services for anything important.",
        ],
      },
      {
        id: "samples",
        h: "3. Sample listings",
        body: [
          "The businesses listed on the site are **sample listings** built from public information to show how the service works. They are not our customers or partners and have not endorsed BlockID. Their shareholders, updates, offerings and dividends are sample data. BlockID's own listing is marked as a self-assessment.",
        ],
      },
      {
        id: "advice",
        h: "4. No offer and no financial advice",
        body: [
          "Nothing on the services is an offer of securities or of any other financial product, an invitation to invest, or financial product advice. Auschain Pty Ltd does not hold an Australian financial services licence.",
          "Fair values, value ranges, business scores and grades are indicative estimates made to demonstrate the service. They are **not a valuation for regulatory, tax, accounting or legal purposes** and are not an independent expert's report. They do not take your objectives, financial situation or needs into account. Get independent professional advice before you make any investment decision.",
        ],
      },
      {
        id: "tokens",
        h: "5. Tokens have no monetary value",
        body: [
          "Share tokens, mirror tokens and dividend tokens (mAUD) created by the services exist only on **test networks**: BlockID EVM (chain id 262626), the Ethereum Hoodi testnet and the HashKey Chain testnet.",
          [
            "They have **no monetary value** and cannot be exchanged for money.",
            "They are not shares in, or claims against, any real company, and they are not legal title to anything.",
            "Test networks can be reset or stopped at any time.",
            "Do not send assets that have real value to any address shown on the services.",
          ],
        ],
      },
      {
        id: "ai",
        h: "6. Automated and AI-generated reports",
        body: [
          "Business reports, valuations, people reports and CV analyses are produced with automated tools, including third-party AI models and web search. They **may be incomplete, out of date or wrong**. We show the sources we used where we can; please check them.",
          "A person reviews and approves a valuation before anything is written to a blockchain (listing, new shares, dividends). Reports are decision support only: the decisions you make with them are yours.",
        ],
      },
      {
        id: "accounts",
        h: "7. Accounts, wallets and the demo account",
        body: [
          [
            "You can sign in with Google, with a key created in your browser, or with your own wallet (for example MetaMask).",
            "A browser key is kept only in that browser. We never receive it and cannot recover it. Back it up if you want to keep access.",
            "You are responsible for your wallet, its keys and everything done with them.",
            "The shared demo account is visible to other visitors: reports made in it can be seen by other signed-in users. Do not enter real personal or confidential information while you use the demo account.",
          ],
        ],
      },
      {
        id: "content",
        h: "8. What you submit and acceptable use",
        body: [
          "You must have the right to submit anything you give us: company information, figures, shareholder details, CVs and details about people.",
          "**People reports (BlockID HR):** only run a report on a person when you have a lawful purpose and that person's consent. The form asks you to confirm consent, and we record that confirmation.",
          "You must not:",
          [
            "use the services to discriminate against anyone unlawfully, for example because of a protected attribute such as age, sex, race, disability or religion;",
            "harass, stalk or profile people, or collect information about them without a lawful reason;",
            "present sample listings or test tokens as real investments;",
            "try to break or bypass security, rate limits or access controls, or overload or scrape the services;",
            "upload anything unlawful or anything that infringes someone else's rights.",
          ],
          "You keep ownership of what you submit. You give us permission to store, process and display it, and to send it to the service providers described in our Privacy Policy, so that we can run the services for you.",
        ],
      },
      {
        id: "chain",
        h: "9. Blockchain records are permanent",
        body: [
          "Some actions write records to public blockchains, for example wallet addresses and token balances, a fingerprint (hash) of an approved report, and the Merkle root of a share register. These records are public and cannot be changed or deleted, even by us. The Privacy Policy explains exactly what is written.",
        ],
      },
      {
        id: "ip",
        h: "10. Intellectual property",
        body: [
          "The services, their design and software, and the BlockID™ brand belong to Auschain Pty Ltd or its licensors. Some code is published as open source; that code is governed by its own licence.",
        ],
      },
      {
        id: "changes",
        h: "11. Changes, suspension and ending",
        body: [
          "We may change, suspend or end any part of the services. We may remove content or suspend access if we reasonably believe these terms have been broken or the services are being misused.",
        ],
      },
      {
        id: "liability",
        h: "12. Liability",
        body: [
          "Nothing in these terms excludes, restricts or changes any right or remedy you have under the Australian Consumer Law that cannot lawfully be excluded.",
          "Apart from those rights, and to the extent the law allows, the services are provided \"as is\". We are not liable for any loss that comes from relying on reports, valuations, scores or test tokens, or for any indirect or consequential loss. Where our liability cannot be excluded but can be limited, it is limited to supplying the services again.",
        ],
      },
      {
        id: "law",
        h: "13. Governing law",
        body: [
          "These terms are governed by the laws of New South Wales, Australia. You and we submit to the non-exclusive jurisdiction of the courts of New South Wales.",
        ],
      },
      {
        id: "update",
        h: "14. Changes to these terms",
        body: [
          "We may update these terms. The date at the top shows the latest version. If a change is significant, we will show a notice on the site. The Privacy Policy is at /privacy.",
        ],
      },
    ],
  },

  privacy: {
    eyebrow: "Legal",
    title: "Privacy Policy",
    lede: "What personal information BlockID collects, why, who we share it with and what you can do about it. It covers eth.blockid.au, hr.blockid.au and scan.blockid.au.",
    sections: [
      {
        id: "who",
        h: "1. Who we are",
        body: [
          "The BlockID services are operated by **Auschain Pty Ltd** (ABN 79 659 615 111). We handle personal information in line with the Privacy Act 1988 (Cth) and the Australian Privacy Principles (APPs).",
          "Privacy contact: admin@blockid.au. A named privacy officer has not been appointed yet; we will list them here when they are.",
        ],
      },
      {
        id: "collect",
        h: "2. What we collect",
        body: [
          [
            "**Wallet address.** When you sign in with MetaMask or a browser key, we receive your public wallet address and the sign-in message you signed. A session cookie keeps you signed in.",
            "**Google sign-in.** If you use Google, we receive your Google account ID, email address, name and profile picture link.",
            "**Browser key.** For people without a wallet, a key is created in your browser and stored there, encrypted. The private key never leaves your browser; we only see its public address.",
            "**Company information you submit:** the website, figures you enter, share code, shareholders (names, wallet addresses and percentages), business updates and KPIs.",
            "**BlockID HR:** the names, roles, bios, links and job descriptions you enter, and CVs. A CV file is read **in your browser**; the file itself is not uploaded. Its text, with email addresses and phone numbers removed in the browser (and again on our server), is sent to our server, analysed and stored with the report.",
            "**People reports.** For a people report we collect public professional information about the named person from public web sources (search results and web pages), store the pages we used as evidence and show them in the report. We do not collect health, religion, political views, family or relationships, home address, phone number, personal email, age or date of birth, ethnicity or sexuality; our system filters these out. We do not scrape LinkedIn.",
            "**Technical data.** Our servers and Cloudflare log requests, including IP address, browser type and the page requested. Visitor statistics use a daily-changing hashed value instead of the raw IP address. We also record usage of AI models (per call, with the user it was for) to manage cost and abuse, and keep an audit log of administrator actions.",
          ],
          "**Cookies and browser storage.** We use one sign-in cookie (HttpOnly, Secure) and browser storage for your language choice and your browser key. We do not use advertising cookies. Cloudflare may run its own performance and security measurements.",
        ],
      },
      {
        id: "use",
        h: "3. How we use it",
        body: [
          [
            "to sign you in and run the services you ask for: valuations, company pages, share registers, people reports and CV analyses;",
            "to show your reports to you and to the people you share them with;",
            "to protect the services: rate limits, abuse prevention, security and audit;",
            "to fix problems and improve the services.",
          ],
          "We do not sell personal information and we do not use it for advertising.",
        ],
      },
      {
        id: "ai",
        h: "4. AI model providers and web search",
        body: [
          "To produce reports we send text to third-party AI model providers: **SambaNova**, **Anthropic (Claude)** and **DeepInfra**. We use them one after another as fallbacks, so any of them may receive a given request.",
          [
            "For business valuations: text from the company's public website (emails and phone numbers removed), search results, and figures the business entered.",
            "For people reports and CV analysis: the names and roles of the people in the report, the bio or CV text you provided (contact details removed), job descriptions, and public pages about them.",
          ],
          "Web searches go to **Brave Search** and to Claude's web search. Search queries can include a company name or a person's name together with a company or role.",
          "These providers are based outside Australia (for example in the United States), so your information may be processed overseas (APP 8). We have not yet signed specific data processing agreements with them; their standard business terms apply. We will update this policy when that changes.",
        ],
      },
      {
        id: "others",
        h: "5. Other service providers",
        body: [
          [
            "**Google Cloud** hosts our server and database.",
            "**Cloudflare** sits in front of our sites (security, network and DNS), so it handles all traffic to them.",
            "**Google** handles Google sign-in and, when we email you, our outgoing email (Google Workspace).",
          ],
          "People you choose to share a report with (for example through a share link) can see that report.",
        ],
      },
      {
        id: "where",
        h: "6. Where your data is stored",
        body: [
          "Our application server and database run on a Google Cloud virtual machine in the Sydney region (australia-southeast1). Cloudflare operates a global network. AI and search providers process data overseas (section 4).",
          "Whether team members outside Australia will have access to production data has not been decided. We will update this policy before that happens.",
        ],
      },
      {
        id: "chain",
        h: "7. What is written to blockchains",
        body: [
          "Blockchain records are **public and permanent**: anyone can read them, and nobody, including us, can change or delete them. We keep personal details off-chain. What we write:",
          [
            "shareholder wallet addresses and their token balances and transfers (BlockID EVM, with mirror balances on Ethereum Hoodi and HashKey Chain testnet);",
            "for each verified holder: a country code, an expiry date and a hash of the off-chain check record, never the record itself;",
            "the company name and share code of the token;",
            "a hash (fingerprint) of each approved valuation report and of approved business updates, and Merkle roots of the share register and of dividend rounds.",
          ],
          "Names, email addresses, CVs and people reports are **not** written to any blockchain.",
        ],
      },
      {
        id: "people",
        h: "8. People reports and consent",
        body: [
          "BlockID HR researches named people, so it has extra rules:",
          [
            "Run a report only with a lawful purpose and the person's consent. The requester must confirm consent; we record who confirmed it and when.",
            "Only public professional information is used (roles, companies, education, publications, awards, skills). A fact is shown as verified only when a stored source supports it; everything else is marked as unconfirmed.",
            "Access is limited to the requester, platform administrators, administrators of the linked company and people with a share link (which the requester can revoke). Reports made in the shared demo account can be seen by any signed-in user.",
            "Anyone named in a report can ask for their details to be removed (section 11).",
          ],
        ],
      },
      {
        id: "adm",
        h: "9. Automated decisions",
        body: [
          "Business scores, value ranges, people scores, fit scores and suggested decisions (such as \"Proceed\" or \"Verify first\") are made by automated processing: AI models suggest some inputs and fixed formulas compute the result. Each report shows its method and sources.",
          "These results are **decision support, not decisions**. A person approves every valuation before anything is written to a blockchain, and a person using a people report makes the decision themselves. People reports must not be the only basis for a decision about someone's employment, credit or investment.",
        ],
      },
      {
        id: "keep",
        h: "10. How long we keep it",
        body: [
          [
            "Server access logs: about 14 days. Error logs: 30 days. Sign-in session records: 45 days.",
            "Reports, CV text, evidence and company data: kept until you delete them or ask us to. An automatic retention period (for example for CVs) has not been set yet; we will publish it here when it is.",
            "Blockchain records cannot be deleted (section 7).",
          ],
        ],
      },
      {
        id: "rights",
        h: "11. Access, correction and deletion",
        body: [
          "You can ask to see, correct or delete the personal information we hold about you, including information in a people report about you. Email admin@blockid.au and tell us which report or account it is about. We may need to confirm who you are. We aim to reply within 30 days.",
          "When we delete a person from a report, we remove their details, facts and stored evidence and recalculate the report; we can also delete a whole report. Records kept for audit show that a deletion happened, not the person's name.",
        ],
      },
      {
        id: "security",
        h: "12. Security",
        body: [
          "We use HTTPS, a secure sign-in cookie, access controls, removal of contact details before AI processing, and an isolated service that alone holds the keys that write to blockchains. The services are a pilot: the smart contracts have not been audited, and no system is completely secure.",
        ],
      },
      {
        id: "complaints",
        h: "13. Complaints",
        body: [
          "If you have a concern about how we handle your information, please email admin@blockid.au first. If you are not satisfied with our answer within 30 days, you can complain to the Office of the Australian Information Commissioner (OAIC): https://www.oaic.gov.au or 1300 363 992.",
        ],
      },
      {
        id: "update",
        h: "14. Changes to this policy",
        body: [
          "We will update this policy when the services change. The date at the top shows the latest version. The Terms of Use are at /terms.",
        ],
      },
    ],
  },
};

export const legalVi: LegalCopy = {
  updated: "Cập nhật lần cuối ngày 29 tháng 9 năm 2026",
  review: "Phiên bản này đang chờ luật sư rà soát. Nội dung mô tả cách dịch vụ hoạt động hiện nay và có thể thay đổi sau khi rà soát. Nếu bản tiếng Việt và bản tiếng Anh khác nhau, bản tiếng Anh được ưu tiên.",
  toc: "Trong trang này",
  other: { terms: "Điều khoản sử dụng", privacy: "Chính sách quyền riêng tư" },
  contactH: "Có câu hỏi?",
  contact: "Viết cho admin@blockid.au. Auschain Pty Ltd · ABN 79 659 615 111 · ACN 659 615 111 · New South Wales, Úc.",

  terms: {
    eyebrow: "Pháp lý",
    title: "Điều khoản sử dụng",
    lede: "Quy định khi dùng BlockID Business Passport (eth.blockid.au), BlockID HR (hr.blockid.au) và trình duyệt khối BlockID (scan.blockid.au). Vui lòng đọc cùng Chính sách quyền riêng tư.",
    sections: [
      {
        id: "who",
        h: "1. Chúng tôi là ai",
        body: [
          "Các dịch vụ BlockID do **Auschain Pty Ltd** (ABN 79 659 615 111, ACN 659 615 111), một công ty tư nhân của Úc, vận hành (\"chúng tôi\"). BlockID™ là nhãn hiệu của Auschain Pty Ltd, chưa được đăng ký.",
          "Khi dùng dịch vụ, bạn đồng ý với các điều khoản này. Nếu không đồng ý, vui lòng không sử dụng dịch vụ.",
        ],
      },
      {
        id: "pilot",
        h: "2. Chương trình thử nghiệm miễn phí trên mạng thử",
        body: [
          "Dịch vụ đang ở giai đoạn thử nghiệm và trình diễn, hiện **miễn phí**: chúng tôi không thu bất kỳ khoản tiền nào. Nếu sau này có gói trả phí, chúng tôi sẽ báo trước và công bố điều khoản mới. Chúng tôi sẽ không thu tiền khi bạn chưa đồng ý.",
          "Vì đây là bản thử nghiệm, tính năng có thể thay đổi, ngừng hoạt động hoặc bị gỡ bỏ, và dữ liệu trên mạng thử có thể bị đặt lại. Đừng dựa vào dịch vụ cho việc quan trọng.",
        ],
      },
      {
        id: "samples",
        h: "3. Hồ sơ mẫu",
        body: [
          "Các doanh nghiệp trên trang là **hồ sơ mẫu** được xây dựng từ thông tin công khai để minh họa cách dịch vụ hoạt động. Họ không phải khách hàng hay đối tác của chúng tôi và không xác nhận BlockID. Cổ đông, bản cập nhật, đợt chào bán và cổ tức của họ là dữ liệu mẫu. Hồ sơ của chính BlockID được đánh dấu là tự đánh giá.",
        ],
      },
      {
        id: "advice",
        h: "4. Không chào bán, không tư vấn tài chính",
        body: [
          "Không nội dung nào trên dịch vụ là chào bán chứng khoán hay sản phẩm tài chính khác, lời mời đầu tư, hay tư vấn về sản phẩm tài chính. Auschain Pty Ltd không có giấy phép dịch vụ tài chính của Úc (AFSL).",
          "Giá trị hợp lý, khoảng giá trị, điểm doanh nghiệp và xếp hạng chỉ là ước tính tham khảo để minh họa dịch vụ. Chúng **không phải là định giá cho mục đích pháp lý, quản lý, thuế hay kế toán** và không phải báo cáo của chuyên gia độc lập. Chúng không xét đến mục tiêu, tình hình tài chính hay nhu cầu của bạn. Hãy hỏi ý kiến chuyên gia độc lập trước khi quyết định đầu tư.",
        ],
      },
      {
        id: "tokens",
        h: "5. Token không có giá trị tiền tệ",
        body: [
          "Token cổ phần, token bản sao và token cổ tức (mAUD) do dịch vụ tạo ra chỉ tồn tại trên **mạng thử**: BlockID EVM (chain id 262626), mạng thử Ethereum Hoodi và mạng thử HashKey Chain.",
          [
            "Chúng **không có giá trị tiền tệ** và không thể đổi ra tiền.",
            "Chúng không phải là cổ phần hay quyền đòi đối với bất kỳ công ty thật nào, và không phải là quyền sở hữu pháp lý đối với bất cứ thứ gì.",
            "Mạng thử có thể bị đặt lại hoặc dừng bất cứ lúc nào.",
            "Đừng gửi tài sản có giá trị thật đến bất kỳ địa chỉ nào hiển thị trên dịch vụ.",
          ],
        ],
      },
      {
        id: "ai",
        h: "6. Báo cáo tự động và do AI tạo",
        body: [
          "Báo cáo doanh nghiệp, định giá, báo cáo về người và phân tích CV được tạo bằng công cụ tự động, gồm mô hình AI của bên thứ ba và tìm kiếm web. Chúng **có thể thiếu, cũ hoặc sai**. Chúng tôi hiển thị nguồn đã dùng khi có thể; hãy tự kiểm tra.",
          "Một người xem xét và phê duyệt định giá trước khi bất cứ điều gì được ghi lên blockchain (niêm yết, phát hành thêm, cổ tức). Báo cáo chỉ hỗ trợ ra quyết định: quyết định là của bạn.",
        ],
      },
      {
        id: "accounts",
        h: "7. Tài khoản, ví và tài khoản demo",
        body: [
          [
            "Bạn có thể đăng nhập bằng Google, bằng khóa tạo trong trình duyệt, hoặc bằng ví của bạn (ví dụ MetaMask).",
            "Khóa trình duyệt chỉ nằm trong trình duyệt đó. Chúng tôi không bao giờ nhận được và không thể khôi phục nó. Hãy sao lưu nếu muốn giữ quyền truy cập.",
            "Bạn chịu trách nhiệm về ví, khóa của ví và mọi thao tác thực hiện bằng chúng.",
            "Tài khoản demo dùng chung được người khác nhìn thấy: báo cáo tạo trong đó có thể được người dùng đã đăng nhập khác xem. Đừng nhập thông tin cá nhân thật hay thông tin mật khi dùng tài khoản demo.",
          ],
        ],
      },
      {
        id: "content",
        h: "8. Nội dung bạn gửi và cách dùng được phép",
        body: [
          "Bạn phải có quyền gửi mọi thứ bạn cung cấp: thông tin công ty, số liệu, thông tin cổ đông, CV và thông tin về người khác.",
          "**Báo cáo về người (BlockID HR):** chỉ chạy báo cáo về một người khi bạn có mục đích hợp pháp và được người đó đồng ý. Biểu mẫu yêu cầu bạn xác nhận sự đồng ý, và chúng tôi lưu lại xác nhận đó.",
          "Bạn không được:",
          [
            "dùng dịch vụ để phân biệt đối xử trái pháp luật, ví dụ vì một đặc điểm được bảo vệ như tuổi, giới tính, chủng tộc, khuyết tật hay tôn giáo;",
            "quấy rối, theo dõi hay lập hồ sơ về người khác, hoặc thu thập thông tin về họ khi không có lý do hợp pháp;",
            "giới thiệu hồ sơ mẫu hay token thử nghiệm như khoản đầu tư thật;",
            "tìm cách phá hoặc vượt qua bảo mật, giới hạn tần suất hay kiểm soát truy cập, hoặc làm quá tải hay thu thập dữ liệu hàng loạt từ dịch vụ;",
            "tải lên nội dung trái pháp luật hoặc xâm phạm quyền của người khác.",
          ],
          "Bạn vẫn sở hữu nội dung mình gửi. Bạn cho phép chúng tôi lưu trữ, xử lý, hiển thị và gửi nội dung đó cho các nhà cung cấp dịch vụ nêu trong Chính sách quyền riêng tư, để vận hành dịch vụ cho bạn.",
        ],
      },
      {
        id: "chain",
        h: "9. Bản ghi blockchain là vĩnh viễn",
        body: [
          "Một số thao tác ghi dữ liệu lên blockchain công khai, ví dụ địa chỉ ví và số dư token, dấu vân tay (hash) của báo cáo đã duyệt, và Merkle root của sổ cổ đông. Các bản ghi này công khai và không thể sửa hay xóa, kể cả bởi chúng tôi. Chính sách quyền riêng tư nêu rõ những gì được ghi.",
        ],
      },
      {
        id: "ip",
        h: "10. Sở hữu trí tuệ",
        body: [
          "Dịch vụ, thiết kế, phần mềm và thương hiệu BlockID™ thuộc về Auschain Pty Ltd hoặc bên cấp phép. Một phần mã nguồn được công bố dưới dạng mã nguồn mở; phần mã đó tuân theo giấy phép riêng của nó.",
        ],
      },
      {
        id: "changes",
        h: "11. Thay đổi, tạm ngừng và chấm dứt",
        body: [
          "Chúng tôi có thể thay đổi, tạm ngừng hoặc chấm dứt bất kỳ phần nào của dịch vụ. Chúng tôi có thể gỡ nội dung hoặc tạm khóa quyền truy cập nếu có cơ sở hợp lý cho rằng các điều khoản này bị vi phạm hoặc dịch vụ bị lạm dụng.",
        ],
      },
      {
        id: "liability",
        h: "12. Trách nhiệm",
        body: [
          "Không điều khoản nào loại trừ, hạn chế hay thay đổi quyền của bạn theo Luật Người tiêu dùng Úc (Australian Consumer Law) mà pháp luật không cho phép loại trừ.",
          "Ngoài các quyền đó, trong phạm vi pháp luật cho phép, dịch vụ được cung cấp \"nguyên trạng\". Chúng tôi không chịu trách nhiệm về tổn thất phát sinh do dựa vào báo cáo, định giá, điểm số hay token thử nghiệm, hoặc về tổn thất gián tiếp. Khi trách nhiệm không thể loại trừ nhưng có thể giới hạn, trách nhiệm đó giới hạn ở việc cung cấp lại dịch vụ.",
        ],
      },
      {
        id: "law",
        h: "13. Luật áp dụng",
        body: [
          "Các điều khoản này chịu sự điều chỉnh của pháp luật bang New South Wales, Úc. Bạn và chúng tôi chấp nhận thẩm quyền không độc quyền của tòa án New South Wales.",
        ],
      },
      {
        id: "update",
        h: "14. Thay đổi điều khoản",
        body: [
          "Chúng tôi có thể cập nhật các điều khoản này. Ngày ở đầu trang cho biết phiên bản mới nhất. Nếu thay đổi quan trọng, chúng tôi sẽ thông báo trên trang. Chính sách quyền riêng tư ở /privacy.",
        ],
      },
    ],
  },

  privacy: {
    eyebrow: "Pháp lý",
    title: "Chính sách quyền riêng tư",
    lede: "BlockID thu thập thông tin cá nhân nào, vì sao, chia sẻ với ai và bạn có thể làm gì. Áp dụng cho eth.blockid.au, hr.blockid.au và scan.blockid.au.",
    sections: [
      {
        id: "who",
        h: "1. Chúng tôi là ai",
        body: [
          "Các dịch vụ BlockID do **Auschain Pty Ltd** (ABN 79 659 615 111) vận hành. Chúng tôi xử lý thông tin cá nhân theo Đạo luật Quyền riêng tư 1988 (Privacy Act 1988) và các Nguyên tắc Quyền riêng tư của Úc (APP).",
          "Liên hệ về quyền riêng tư: admin@blockid.au. Chúng tôi chưa bổ nhiệm cán bộ phụ trách quyền riêng tư; tên người đó sẽ được ghi ở đây khi có.",
        ],
      },
      {
        id: "collect",
        h: "2. Chúng tôi thu thập gì",
        body: [
          [
            "**Địa chỉ ví.** Khi bạn đăng nhập bằng MetaMask hoặc khóa trình duyệt, chúng tôi nhận địa chỉ ví công khai và thông điệp đăng nhập bạn đã ký. Một cookie phiên giữ trạng thái đăng nhập.",
            "**Đăng nhập Google.** Nếu dùng Google, chúng tôi nhận mã tài khoản Google, địa chỉ email, tên và liên kết ảnh đại diện.",
            "**Khóa trình duyệt.** Với người không có ví, một khóa được tạo và lưu mã hóa ngay trong trình duyệt. Khóa bí mật không bao giờ rời trình duyệt; chúng tôi chỉ thấy địa chỉ công khai.",
            "**Thông tin công ty bạn gửi:** website, số liệu bạn nhập, mã cổ phần, cổ đông (tên, địa chỉ ví, tỷ lệ), bản cập nhật và chỉ số kinh doanh.",
            "**BlockID HR:** tên, vai trò, tiểu sử, liên kết và mô tả công việc bạn nhập, và CV. Tệp CV được đọc **ngay trong trình duyệt**; bản thân tệp không được tải lên. Văn bản của CV, sau khi đã xóa email và số điện thoại trong trình duyệt (và xóa lại trên máy chủ), được gửi đến máy chủ để phân tích và lưu cùng báo cáo.",
            "**Báo cáo về người.** Chúng tôi thu thập thông tin nghề nghiệp công khai về người được nêu tên từ các nguồn web công khai (kết quả tìm kiếm, trang web), lưu các trang đã dùng làm bằng chứng và hiển thị trong báo cáo. Chúng tôi không thu thập thông tin về sức khỏe, tôn giáo, quan điểm chính trị, gia đình hay quan hệ, địa chỉ nhà, số điện thoại, email cá nhân, tuổi hay ngày sinh, dân tộc hay xu hướng tính dục; hệ thống lọc bỏ các thông tin này. Chúng tôi không thu thập dữ liệu từ LinkedIn.",
            "**Dữ liệu kỹ thuật.** Máy chủ và Cloudflare ghi nhật ký truy cập, gồm địa chỉ IP, loại trình duyệt và trang được yêu cầu. Thống kê lượt truy cập dùng giá trị băm đổi mỗi ngày thay cho địa chỉ IP gốc. Chúng tôi cũng ghi lại việc dùng mô hình AI (theo từng lần gọi, kèm người dùng liên quan) để quản lý chi phí và chống lạm dụng, và lưu nhật ký thao tác của quản trị viên.",
          ],
          "**Cookie và bộ nhớ trình duyệt.** Chúng tôi dùng một cookie đăng nhập (HttpOnly, Secure) và bộ nhớ trình duyệt cho lựa chọn ngôn ngữ và khóa trình duyệt. Chúng tôi không dùng cookie quảng cáo. Cloudflare có thể tự đo hiệu năng và bảo mật.",
        ],
      },
      {
        id: "use",
        h: "3. Chúng tôi dùng thông tin thế nào",
        body: [
          [
            "để đăng nhập và chạy các dịch vụ bạn yêu cầu: định giá, trang công ty, sổ cổ đông, báo cáo về người và phân tích CV;",
            "để hiển thị báo cáo cho bạn và cho người bạn chia sẻ;",
            "để bảo vệ dịch vụ: giới hạn tần suất, chống lạm dụng, bảo mật và kiểm toán;",
            "để sửa lỗi và cải thiện dịch vụ.",
          ],
          "Chúng tôi không bán thông tin cá nhân và không dùng nó cho quảng cáo.",
        ],
      },
      {
        id: "ai",
        h: "4. Nhà cung cấp mô hình AI và tìm kiếm web",
        body: [
          "Để tạo báo cáo, chúng tôi gửi văn bản đến các nhà cung cấp mô hình AI bên thứ ba: **SambaNova**, **Anthropic (Claude)** và **DeepInfra**. Chúng được dùng lần lượt để dự phòng, nên bất kỳ nhà cung cấp nào cũng có thể nhận một yêu cầu.",
          [
            "Với định giá doanh nghiệp: văn bản từ website công khai của công ty (đã xóa email và số điện thoại), kết quả tìm kiếm và số liệu doanh nghiệp đã nhập.",
            "Với báo cáo về người và phân tích CV: tên và vai trò của những người trong báo cáo, tiểu sử hoặc văn bản CV bạn cung cấp (đã xóa thông tin liên hệ), mô tả công việc, và các trang công khai về họ.",
          ],
          "Tìm kiếm web được gửi đến **Brave Search** và công cụ tìm kiếm web của Claude. Câu truy vấn có thể chứa tên công ty hoặc tên một người kèm công ty hay vai trò.",
          "Các nhà cung cấp này ở ngoài nước Úc (ví dụ Hoa Kỳ), nên thông tin của bạn có thể được xử lý ở nước ngoài (APP 8). Chúng tôi chưa ký thỏa thuận xử lý dữ liệu riêng với họ; điều khoản kinh doanh tiêu chuẩn của họ được áp dụng. Chúng tôi sẽ cập nhật chính sách này khi điều đó thay đổi.",
        ],
      },
      {
        id: "others",
        h: "5. Các nhà cung cấp dịch vụ khác",
        body: [
          [
            "**Google Cloud** lưu trữ máy chủ và cơ sở dữ liệu.",
            "**Cloudflare** đứng trước các trang của chúng tôi (bảo mật, mạng và DNS), nên xử lý toàn bộ lưu lượng đến các trang.",
            "**Google** xử lý đăng nhập Google và, khi chúng tôi gửi email cho bạn, email gửi đi (Google Workspace).",
          ],
          "Người bạn chọn chia sẻ báo cáo (ví dụ qua liên kết chia sẻ) có thể xem báo cáo đó.",
        ],
      },
      {
        id: "where",
        h: "6. Dữ liệu được lưu ở đâu",
        body: [
          "Máy chủ ứng dụng và cơ sở dữ liệu chạy trên một máy ảo Google Cloud ở vùng Sydney (australia-southeast1). Cloudflare vận hành mạng toàn cầu. Nhà cung cấp AI và tìm kiếm xử lý dữ liệu ở nước ngoài (mục 4).",
          "Việc thành viên nhóm ở ngoài nước Úc có được truy cập dữ liệu vận hành hay không vẫn chưa được quyết định. Chúng tôi sẽ cập nhật chính sách này trước khi điều đó xảy ra.",
        ],
      },
      {
        id: "chain",
        h: "7. Những gì được ghi lên blockchain",
        body: [
          "Bản ghi blockchain là **công khai và vĩnh viễn**: ai cũng đọc được, và không ai, kể cả chúng tôi, có thể sửa hay xóa. Chúng tôi giữ thông tin cá nhân ngoài chuỗi. Những gì được ghi:",
          [
            "địa chỉ ví của cổ đông cùng số dư và giao dịch chuyển token (BlockID EVM, kèm số dư bản sao trên Ethereum Hoodi và HashKey Chain testnet);",
            "với mỗi cổ đông đã xác minh: mã quốc gia, ngày hết hạn và giá trị băm của hồ sơ kiểm tra ngoài chuỗi, không bao giờ là bản thân hồ sơ;",
            "tên công ty và mã cổ phần của token;",
            "giá trị băm (dấu vân tay) của mỗi báo cáo định giá và bản cập nhật kinh doanh đã duyệt, và Merkle root của sổ cổ đông và của các đợt cổ tức.",
          ],
          "Tên, email, CV và báo cáo về người **không** được ghi lên bất kỳ blockchain nào.",
        ],
      },
      {
        id: "people",
        h: "8. Báo cáo về người và sự đồng ý",
        body: [
          "BlockID HR tìm hiểu về những người được nêu tên, nên có thêm quy định:",
          [
            "Chỉ chạy báo cáo khi có mục đích hợp pháp và được người đó đồng ý. Người yêu cầu phải xác nhận sự đồng ý; chúng tôi ghi lại ai xác nhận và lúc nào.",
            "Chỉ dùng thông tin nghề nghiệp công khai (vai trò, công ty, học vấn, ấn phẩm, giải thưởng, kỹ năng). Một thông tin chỉ được ghi là đã xác minh khi có nguồn đã lưu chứng minh; phần còn lại được ghi là chưa xác nhận.",
            "Quyền xem giới hạn cho người yêu cầu, quản trị viên nền tảng, quản trị viên của công ty liên kết và người có liên kết chia sẻ (người yêu cầu có thể thu hồi). Báo cáo tạo trong tài khoản demo dùng chung có thể được mọi người dùng đã đăng nhập xem.",
            "Bất kỳ ai có tên trong báo cáo đều có thể yêu cầu gỡ thông tin của mình (mục 11).",
          ],
        ],
      },
      {
        id: "adm",
        h: "9. Quyết định tự động",
        body: [
          "Điểm doanh nghiệp, khoảng giá trị, điểm về người, điểm phù hợp và quyết định gợi ý (như \"Tiếp tục\" hay \"Xác minh trước\") được tạo bằng xử lý tự động: mô hình AI gợi ý một số dữ liệu đầu vào và công thức cố định tính ra kết quả. Mỗi báo cáo hiển thị phương pháp và nguồn.",
          "Các kết quả này **hỗ trợ ra quyết định, không phải là quyết định**. Một người phê duyệt mọi định giá trước khi bất cứ điều gì được ghi lên blockchain, và người dùng báo cáo về người tự đưa ra quyết định. Báo cáo về người không được là căn cứ duy nhất cho quyết định về việc làm, tín dụng hay đầu tư liên quan đến một người.",
        ],
      },
      {
        id: "keep",
        h: "10. Chúng tôi lưu giữ bao lâu",
        body: [
          [
            "Nhật ký truy cập máy chủ: khoảng 14 ngày. Nhật ký lỗi: 30 ngày. Bản ghi phiên đăng nhập: 45 ngày.",
            "Báo cáo, văn bản CV, bằng chứng và dữ liệu công ty: lưu đến khi bạn xóa hoặc yêu cầu chúng tôi xóa. Thời hạn tự động xóa (ví dụ cho CV) chưa được quyết định; chúng tôi sẽ công bố ở đây khi có.",
            "Bản ghi blockchain không thể xóa (mục 7).",
          ],
        ],
      },
      {
        id: "rights",
        h: "11. Truy cập, chỉnh sửa và xóa",
        body: [
          "Bạn có thể yêu cầu xem, sửa hoặc xóa thông tin cá nhân chúng tôi giữ về bạn, kể cả thông tin trong báo cáo về bạn. Gửi email đến admin@blockid.au và cho biết báo cáo hoặc tài khoản liên quan. Chúng tôi có thể cần xác minh danh tính của bạn. Chúng tôi cố gắng trả lời trong vòng 30 ngày.",
          "Khi xóa một người khỏi báo cáo, chúng tôi gỡ thông tin, dữ kiện và bằng chứng đã lưu của người đó và tính lại báo cáo; chúng tôi cũng có thể xóa cả báo cáo. Nhật ký kiểm toán chỉ ghi lại việc đã xóa, không ghi tên người đó.",
        ],
      },
      {
        id: "security",
        h: "12. Bảo mật",
        body: [
          "Chúng tôi dùng HTTPS, cookie đăng nhập an toàn, kiểm soát truy cập, xóa thông tin liên hệ trước khi xử lý bằng AI, và một dịch vụ tách biệt là nơi duy nhất giữ khóa ghi lên blockchain. Dịch vụ đang thử nghiệm: hợp đồng thông minh chưa được kiểm toán, và không hệ thống nào an toàn tuyệt đối.",
        ],
      },
      {
        id: "complaints",
        h: "13. Khiếu nại",
        body: [
          "Nếu bạn lo ngại về cách chúng tôi xử lý thông tin, vui lòng email admin@blockid.au trước. Nếu không hài lòng với câu trả lời trong vòng 30 ngày, bạn có thể khiếu nại đến Văn phòng Ủy viên Thông tin Úc (OAIC): https://www.oaic.gov.au hoặc 1300 363 992.",
        ],
      },
      {
        id: "update",
        h: "14. Thay đổi chính sách",
        body: [
          "Chúng tôi sẽ cập nhật chính sách này khi dịch vụ thay đổi. Ngày ở đầu trang cho biết phiên bản mới nhất. Điều khoản sử dụng ở /terms.",
        ],
      },
    ],
  },
};
