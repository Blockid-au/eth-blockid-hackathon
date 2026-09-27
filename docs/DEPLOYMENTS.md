# Deployments and tokens

_Generated 2026-09-27 11:50 UTC by `scripts/export-deployments.py` from Postgres + live on-chain reads. Do not edit by hand; re-run the script._

## Networks

| Chain | Chain ID | Explorer | Role |
|---|---|---|---|
| BlockID Chain | 262626 | https://scan.blockid.au | register of record (live, transferable) |
| Ethereum Hoodi | 560048 | https://hoodi.etherscan.io | paused mirror + Merkle anchor |
| HashKey Chain testnet | 133 | https://testnet-explorer.hskchain.net | paused mirror + Merkle anchor |

## Company share tokens

Each company is issued on BlockID Chain (live token, KYC-gated) and mirrored to Hoodi and HashKey testnet as a **paused** token whose balances follow BlockID Chain; every change re-anchors a Merkle root of the cap table. Supply is checked on all three chains at generation time.

| Ticker | Company | Status | Holders | Total supply | BlockID Chain | Hoodi | HSK testnet | Supply check |
|---|---|---|---|---|---|---|---|---|
| **GAA** | Go1 | anchored | 4 | 79,420,000 | [`0xD40D…E058`](https://scan.blockid.au/token/0xD40D9cb55b56b508A9Ee09E3967dAe14a6a0E058) | [`0xC5Ff…B836`](https://hoodi.etherscan.io/token/0xC5FfBF5D90Dc5BA5B5a8D0dA05227aFB809aB836) | [`0x78ad…b15b`](https://testnet-explorer.hskchain.net/token/0x78ad540acC4D1499Ce3a2703694e12BA02C8b15b) | ✅ equal on 3 chains |
| **ART** | Airtasker | anchored | 14 | 82,358,641 | [`0xbfcd…BdC9`](https://scan.blockid.au/token/0xbfcd472d4E7B39b46EB08e2B402E8a70949EBdC9) | [`0xFBC2…D8eE`](https://hoodi.etherscan.io/token/0xFBC24e29039fc0a51f0067D5f03749cE30BCD8eE) | [`0x25Dd…eF53`](https://testnet-explorer.hskchain.net/token/0x25Dde7f360540dF299F7b07ca23F88159dc7eF53) | ✅ equal on 3 chains |
| **EHE** | Employment Hero | anchored | 4 | 70,200,000 | [`0x0C00…36DA`](https://scan.blockid.au/token/0x0C00eF751244ea28f16993801BC18Def7Ed936DA) | [`0x78f3…1655`](https://hoodi.etherscan.io/token/0x78f30c9D075639e05b479a16f1B1bA95f4551655) | [`0x1227…F7d7`](https://testnet-explorer.hskchain.net/token/0x1227dF98AD0a415E38fddcab7a62fCA1C87aF7d7) | ✅ equal on 3 chains |
| **MOM** | MoMo | anchored | 4 | 70,200,000 | [`0x3A2c…ACf3`](https://scan.blockid.au/token/0x3A2c73d9602201F1053fa09EA2d22A15aE65ACf3) | [`0x8812…C53a`](https://hoodi.etherscan.io/token/0x88124019Ff2C061FCB67cb2dB71bC583eDf4C53a) | [`0xE13D…9126`](https://testnet-explorer.hskchain.net/token/0xE13D5b04CEA90F131B97020174482323C1E79126) | ✅ equal on 3 chains |
| **SFT** | SafetyCulture | anchored | 4 | 67,000,000 | [`0x9aD5…5a6c`](https://scan.blockid.au/token/0x9aD5034836bD51FD9372a117e1De6E0c7D4d5a6c) | [`0xE13D…9126`](https://hoodi.etherscan.io/token/0xE13D5b04CEA90F131B97020174482323C1E79126) | [`0x9dD5…38BF`](https://testnet-explorer.hskchain.net/token/0x9dD57C9aD0C12c9e937025B01FA4F77a8C9238BF) | ✅ equal on 3 chains |
| **BVN** | Base.vn | anchored | 4 | 70,200,000 | [`0xB39E…DF3a`](https://scan.blockid.au/token/0xB39ECb6c83473a0aEE5C7c51fA42183C5A3BDF3a) | [`0xfbb6…74BD`](https://hoodi.etherscan.io/token/0xfbb656fb479a0B193148D2Ba18951306d0f274BD) | [`0x4D9F…1E79`](https://testnet-explorer.hskchain.net/token/0x4D9F238D348C06Bd1c95d5D932B45f1688771E79) | ✅ equal on 3 chains |
| **EBA** | ETH BlockID Australia | anchored | 3 | 3,650,000 | [`0x95A5…8718`](https://scan.blockid.au/token/0x95A5a4b82897087B2c044b653B8e6bd617a58718) | [`0x1a30…Ab3b`](https://hoodi.etherscan.io/token/0x1a305fdD461002BD6136476A69F3a268F79aAb3b) | [`0x041E…bc90`](https://testnet-explorer.hskchain.net/token/0x041Eb1B727c4cdDfc8D46f1fBCb812E1c94fbc90) | ✅ equal on 3 chains |
| **ARW** | Airwallex | anchored | 15 | 5,712,714,601 | [`0x720b…74F9`](https://scan.blockid.au/token/0x720b9cDAf1CfC9fB5d8DdCad8898F1B7684b74F9) | [`0xbf80…9a9b`](https://hoodi.etherscan.io/token/0xbf802637a6Ce2B48A6aaBa74FC907b6595C29a9b) | [`0x3591…Bf88`](https://testnet-explorer.hskchain.net/token/0x35913D5837CD2e223F5909028eD3874d5Dc5Bf88) | ✅ equal on 3 chains |
| **VBC** | Vietnamblockchain | anchored | 2 | 52,800,000 | [`0x3Bc0…f2fa`](https://scan.blockid.au/token/0x3Bc01D7c114B81758EcDcdA61083E18cAd4df2fa) | [`0x2FfE…C2e6`](https://hoodi.etherscan.io/token/0x2FfECD9E6ef98c4F65da716b788cB85f05F8C2e6) | [`0xbF3E…D302`](https://testnet-explorer.hskchain.net/token/0xbF3ED53c16EE12EFa59040feB52DAf4d222BD302) | ✅ equal on 3 chains |
| **SVI** | Startupvalueindex | anchored | 2 | 57,200,000 | [`0xa3E0…d8b6`](https://scan.blockid.au/token/0xa3E09b2EC28777668a8Cad6932f69Bb5DFB5d8b6) | [`0x718a…E454`](https://hoodi.etherscan.io/token/0x718a30741C341DB88C06b4C025579BbC817fE454) | [`0xe466…60e2`](https://testnet-explorer.hskchain.net/token/0xe46635467184157e7618489e650AF686F36060e2) | ✅ equal on 3 chains |
| **DPT** | Deputy | anchored | 3 | 60,600,000 | [`0xfa17…e285`](https://scan.blockid.au/token/0xfa176608B8B51a8db620Da116E6753785803e285) | [`0xfa17…e285`](https://hoodi.etherscan.io/token/0xfa176608B8B51a8db620Da116E6753785803e285) | [`0xb8F9…1204`](https://testnet-explorer.hskchain.net/token/0xb8F909F8A2d8FdB41dBa2CaEe6b99A274da51204) | ✅ equal on 3 chains |
| **CNV** | Canva | anchored | 5 | 70,512,750,000 | [`0x209D…Cc30`](https://scan.blockid.au/token/0x209D5009b93ec4be4C399544b8eB74a21A89Cc30) | [`0x5279…38B4`](https://hoodi.etherscan.io/token/0x527985c7A65Aeb8c0e4fb0c73d7Dfef3B9e238B4) | [`0x3709…d2b9`](https://testnet-explorer.hskchain.net/token/0x370977A0303D5F7047dF28875c18044CACd8d2b9) | ✅ equal on 3 chains |
| **BLC** | Blockid | anchored | 3 | 3,712,000 | [`0xE281…4Ee3`](https://scan.blockid.au/token/0xE2818A32F2e52dB040D272a9350Dd705356d4Ee3) | [`0x38DF…C0Fc`](https://hoodi.etherscan.io/token/0x38DFf5A120908640613a36d7C5056EC7F377C0Fc) | [`0x41eA…e6d7`](https://testnet-explorer.hskchain.net/token/0x41eAeFdf3f31dd692De39B124D1F5BB15761e6d7) | ✅ equal on 3 chains |
| **AST** | Australiablockchain | anchored | 2 | 63,200,000 | [`0xFb9c…eDc3`](https://scan.blockid.au/token/0xFb9c93d126B0C4e11B94070C540807f006FdeDc3) | [`0x02e7…dd28`](https://hoodi.etherscan.io/token/0x02e70420f4A735a6329fdeD334F0E8F5EE8cdd28) | [`0x9679…108E`](https://testnet-explorer.hskchain.net/token/0x9679E00E17eF6ec5b7d5181A02D35e798C0f108E) | ✅ equal on 3 chains |

### Full addresses

| Ticker | Contract | BlockID Chain | Hoodi | HSK testnet |
|---|---|---|---|---|
| GAA | Share token | `0xD40D9cb55b56b508A9Ee09E3967dAe14a6a0E058` | `0xC5FfBF5D90Dc5BA5B5a8D0dA05227aFB809aB836` | `0x78ad540acC4D1499Ce3a2703694e12BA02C8b15b` |
| GAA | Identity registry | `0x0107a9aF204113baD3a47a5BF23d84a3302A8cc1` | `0x2CF282E415707cA6735125Bd003417A9AB57AE33` | `0x7878737BC74885618BFaCf16295FAC54529bf136` |
| GAA | Dividend distributor | `0x728c834DE493DC3e9Ae2f7C0e79d86701B6F9F04` | – | – |
| ART | Share token | `0xbfcd472d4E7B39b46EB08e2B402E8a70949EBdC9` | `0xFBC24e29039fc0a51f0067D5f03749cE30BCD8eE` | `0x25Dde7f360540dF299F7b07ca23F88159dc7eF53` |
| ART | Identity registry | `0x1a712773611128AA23D14Ee32653E0E06Ea6Bc83` | `0xf8B11Ac24091F56428017ACa019091128CF3D347` | `0x43616f6cD253568e0112E6ffe73481bA715F04EA` |
| ART | Dividend distributor | `0x041Eb1B727c4cdDfc8D46f1fBCb812E1c94fbc90` | – | – |
| EHE | Share token | `0x0C00eF751244ea28f16993801BC18Def7Ed936DA` | `0x78f30c9D075639e05b479a16f1B1bA95f4551655` | `0x1227dF98AD0a415E38fddcab7a62fCA1C87aF7d7` |
| EHE | Identity registry | `0x603cF3D9E9D1D575bB0b45456176eD55eF31E4A5` | `0x98D736f1f78C4fEA1C194aA48D34ECB593c33239` | `0x88124019Ff2C061FCB67cb2dB71bC583eDf4C53a` |
| EHE | Dividend distributor | `0x090BB46c67578Fe158f8CaaC9f818a3c7fbC1f67` | – | – |
| MOM | Share token | `0x3A2c73d9602201F1053fa09EA2d22A15aE65ACf3` | `0x88124019Ff2C061FCB67cb2dB71bC583eDf4C53a` | `0xE13D5b04CEA90F131B97020174482323C1E79126` |
| MOM | Identity registry | `0xf522BFa3C2C68A051A67a664A70197B7d439860A` | `0xc024aB56011e93Cfd3fa7152104599d4e062e9Fd` | `0x58087Db122Bb1C3c73e76B47e670f17faebb8Ae0` |
| MOM | Dividend distributor | `0x06Ff0a248aEa8EFB387EDad81240eb01D7E12EE6` | – | – |
| SFT | Share token | `0x9aD5034836bD51FD9372a117e1De6E0c7D4d5a6c` | `0xE13D5b04CEA90F131B97020174482323C1E79126` | `0x9dD57C9aD0C12c9e937025B01FA4F77a8C9238BF` |
| SFT | Identity registry | `0x539c25ED66F2ABFA758a704944426Ef57BC42143` | `0x58087Db122Bb1C3c73e76B47e670f17faebb8Ae0` | `0xB6943fDaE27B99C370c4e731a06cbaAF03Aa7160` |
| SFT | Dividend distributor | `0x845b669F24fc09aa6a302CF0071f2A1c9E66C2E2` | – | – |
| BVN | Share token | `0xB39ECb6c83473a0aEE5C7c51fA42183C5A3BDF3a` | `0xfbb656fb479a0B193148D2Ba18951306d0f274BD` | `0x4D9F238D348C06Bd1c95d5D932B45f1688771E79` |
| BVN | Identity registry | `0x88529cf7c5242C1F2acb3760EdfCd98B283F883d` | `0x9dD57C9aD0C12c9e937025B01FA4F77a8C9238BF` | `0x1410c4413aB2a3dF2923B7c6c3bFeF8De622E422` |
| BVN | Dividend distributor | `0x9dD57C9aD0C12c9e937025B01FA4F77a8C9238BF` | – | – |
| EBA | Share token | `0x95A5a4b82897087B2c044b653B8e6bd617a58718` | `0x1a305fdD461002BD6136476A69F3a268F79aAb3b` | `0x041Eb1B727c4cdDfc8D46f1fBCb812E1c94fbc90` |
| EBA | Identity registry | `0x4D9F238D348C06Bd1c95d5D932B45f1688771E79` | `0x95A5a4b82897087B2c044b653B8e6bd617a58718` | `0xE56dFFF7c673db5e90020fE991a000Fa09D8AadB` |
| EBA | Dividend distributor | `0x9E87d97a098aCBdBb36de3ef75E5fc6d5Dea1bc1` | – | – |
| ARW | Share token | `0x720b9cDAf1CfC9fB5d8DdCad8898F1B7684b74F9` | `0xbf802637a6Ce2B48A6aaBa74FC907b6595C29a9b` | `0x35913D5837CD2e223F5909028eD3874d5Dc5Bf88` |
| ARW | Identity registry | `0xff15D41E9c32a6D52Aaf8657c55971Adbb469E9C` | `0x720b9cDAf1CfC9fB5d8DdCad8898F1B7684b74F9` | `0x1E3f68B47C922c970523Fab7D49599fC99cBf826` |
| ARW | Dividend distributor | `0x3432D2484A83D0c37e5eaeC1458202e30a1693CA` | – | – |
| VBC | Share token | `0x3Bc01D7c114B81758EcDcdA61083E18cAd4df2fa` | `0x2FfECD9E6ef98c4F65da716b788cB85f05F8C2e6` | `0xbF3ED53c16EE12EFa59040feB52DAf4d222BD302` |
| VBC | Identity registry | `0x4FC2d31eB6A0d25F2AeF48CF87BBF5a59B5622fE` | `0x3Bc01D7c114B81758EcDcdA61083E18cAd4df2fa` | `0x42f213A78845dE0C67699Fbd8eB653AdDd8EBC81` |
| VBC | Dividend distributor | `0x30749B9beeFa96f173Bd08beac83bE937240f04A` | – | – |
| SVI | Share token | `0xa3E09b2EC28777668a8Cad6932f69Bb5DFB5d8b6` | `0x718a30741C341DB88C06b4C025579BbC817fE454` | `0xe46635467184157e7618489e650AF686F36060e2` |
| SVI | Identity registry | `0x2bFDD817628D4d4023BA1F39fbfE00E45d33ad1b` | `0xa3E09b2EC28777668a8Cad6932f69Bb5DFB5d8b6` | `0x30749B9beeFa96f173Bd08beac83bE937240f04A` |
| SVI | Dividend distributor | `0x43bF4682Abb06e72adFb0873357427f91bCc1Da5` | – | – |
| DPT | Share token | `0xfa176608B8B51a8db620Da116E6753785803e285` | `0xfa176608B8B51a8db620Da116E6753785803e285` | `0xb8F909F8A2d8FdB41dBa2CaEe6b99A274da51204` |
| DPT | Identity registry | `0x062883c01cD927E3c7A3778385d566c963CAE54B` | `0x062883c01cD927E3c7A3778385d566c963CAE54B` | `0x43bF4682Abb06e72adFb0873357427f91bCc1Da5` |
| DPT | Dividend distributor | `0x6462D6D073B27e3eC29ff4a40CE5FD87430767cb` | – | – |
| CNV | Share token | `0x209D5009b93ec4be4C399544b8eB74a21A89Cc30` | `0x527985c7A65Aeb8c0e4fb0c73d7Dfef3B9e238B4` | `0x370977A0303D5F7047dF28875c18044CACd8d2b9` |
| CNV | Identity registry | `0x527985c7A65Aeb8c0e4fb0c73d7Dfef3B9e238B4` | `0x0FD3CB2b336973E7bfb8E82c9302aF8793B4FaD1` | `0x6462D6D073B27e3eC29ff4a40CE5FD87430767cb` |
| CNV | Dividend distributor | `0x9b11fE156f84a786Da14C7486960ccBc4b11bA30` | – | – |
| BLC | Share token | `0xE2818A32F2e52dB040D272a9350Dd705356d4Ee3` | `0x38DFf5A120908640613a36d7C5056EC7F377C0Fc` | `0x41eAeFdf3f31dd692De39B124D1F5BB15761e6d7` |
| BLC | Identity registry | `0xca36181FC85f6d0a08A861CA8B2a0E77C1573f4E` | `0x3366de4CDcb568e836e1b3FC03617FB803DdA64C` | `0x5389b38Bed58AEA88Fba56eE698875766898faA7` |
| BLC | Dividend distributor | `0x8fC9f399D31E335Ba2cB024C3901f23f9cE58AC2` | – | – |
| AST | Share token | `0xFb9c93d126B0C4e11B94070C540807f006FdeDc3` | `0x02e70420f4A735a6329fdeD334F0E8F5EE8cdd28` | `0x9679E00E17eF6ec5b7d5181A02D35e798C0f108E` |
| AST | Identity registry | `0xBE31C101f3ed0441180826CA465891b327C6f1B5` | `0x4E8181da4F882F6e9EabED96b0EA87A8E32cC2E2` | `0xe8552c7fc89498Ec17954449236d59E8746ee4e9` |
| AST | Dividend distributor | `0x9730F1fD5b7b5F1EFFf36357917500f3d61bE6C3` | – | – |

## Platform and demo contracts

**`hoodi-demo.json`** (chain 560048)

| Name | Address |
|---|---|
| dividendDistributor | `0x112C26D5f5d602293f1a00029f5E375763e70282` |
| identityRegistry | `0x6B96bcE8937e1416Ec1DAC4ADAdD71FE879F8e84` |
| operator | `0x2567Bb502ac840cF93957C60A410160a8cCb5ddf` |
| payToken | `0xB8F96Eb528C563bFf04661F4062A5799A97D0FcA` |
| relayer | `0x1B43f0d3297F79cE6c8BbA12F4FadFBE9112DA4a` |
| shareToken | `0xf3156Ad6eA559096D4aF350b39984408c764698E` |

**`hsk-demo.json`** (chain 133)

| Name | Address |
|---|---|
| agentProvenance | `0x6B96bcE8937e1416Ec1DAC4ADAdD71FE879F8e84` |
| approver | `0xC40052702B48631C26AD7c88b499bF230faCa21F` |
| capTableAnchor | `0x728c834DE493DC3e9Ae2f7C0e79d86701B6F9F04` |
| dividendDistributor | `0xc0Ad2C03f04ce656Ba5820531a6E45d85C37511e` |
| identityRegistry | `0x985cd14495320b1adb2Eb170B62db19b12e901Eb` |
| operator | `0x2567Bb502ac840cF93957C60A410160a8cCb5ddf` |
| payToken | `0xD40D9cb55b56b508A9Ee09E3967dAe14a6a0E058` |
| relayer | `0x1B43f0d3297F79cE6c8BbA12F4FadFBE9112DA4a` |
| shareToken | `0x0107a9aF204113baD3a47a5BF23d84a3302A8cc1` |

**`platform-262626.json`** (chain 262626)

| Name | Address |
|---|---|
| demoAUD | `0x286C1eD22A741F4939A3C7637011B0fAE2C7FFBc` |
| deployer | `0x2567Bb502ac840cF93957C60A410160a8cCb5ddf` |
| issuer | `0x2567Bb502ac840cF93957C60A410160a8cCb5ddf` |

**`platform-560048.json`** (chain 560048)

| Name | Address |
|---|---|
| capTableAnchor | `0xF3dC95D5d207dE9f2aC98184Fd32b45B72334263` |
| deployer | `0x2567Bb502ac840cF93957C60A410160a8cCb5ddf` |
| issuer | `0x2567Bb502ac840cF93957C60A410160a8cCb5ddf` |

## BlockID Chain gas

- `eth_gasPrice` = 0 wei; node `minimum-gas-prices = 0ablkd`.
- feemarket: `no_base_fee=True`, `base_fee=0.000000000000000000`, `min_gas_price=0.000000000000000000`.
- Native token: **BLKD** (base denom `ablkd`, 18 decimals).
- Governance proposal #1 “BlockID EVM: zero gas fees”: PASSED (voting ends 2026-09-27 04:08 UTC).
