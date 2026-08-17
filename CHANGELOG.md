# Changelog

## [3.6.0](https://github.com/smorinlabs/template-press/compare/v3.5.0...v3.6.0) (2026-08-17)


### Features

* **rebrand:** declared file removal ([9a61523](https://github.com/smorinlabs/template-press/commit/9a61523975e012c34c779f564c2e94257059241e))
* **rebrand:** declared file removal ([4f05507](https://github.com/smorinlabs/template-press/commit/4f05507634e261c902f7d1daabc03ef3b3664faf))
* **rebrand:** declared verify exemption with required reason ([b53a348](https://github.com/smorinlabs/template-press/commit/b53a34831e3a184a622a6161dbc8ccdc92f6e6e0))
* **rebrand:** declared verify exemption with required reason ([fc4f8d6](https://github.com/smorinlabs/template-press/commit/fc4f8d66dce9953beb0dc1ccd8c727799ac8ec11))


### Bug Fixes

* **rebrand:** declared reason wins for capped outputs; reject unicode controls ([dc27b7c](https://github.com/smorinlabs/template-press/commit/dc27b7ccf0b5fc5d851d375f08e2483036dcb38e))
* **rebrand:** harden the declared reason — control chars, dead config, verbatim receipt ([f5944e2](https://github.com/smorinlabs/template-press/commit/f5944e2804561a57c8b764fe2e51ba201441e172))
* **rebrand:** receipt-aware removal lifecycle, regen conflicts, reason hygiene ([5acaa9d](https://github.com/smorinlabs/template-press/commit/5acaa9dab98d4e64ae91718558c8c9cf910b94b9))
* **rebrand:** sandbox ancestor guard and receipt carry-forward hardening ([d79fda5](https://github.com/smorinlabs/template-press/commit/d79fda5555a97d4b93a564998fa7035e3d231400))
* **rebrand:** source-coordinate removal records, receipt-chain carry-forward, config hardening ([36a79d5](https://github.com/smorinlabs/template-press/commit/36a79d5d3331466ca7e0d2e33de5785e67fe703b))

## [3.5.0](https://github.com/smorinlabs/template-press/compare/v3.4.0...v3.5.0) (2026-08-17)


### Features

* **rebrand:** add native platform regeneration ([7d77ca7](https://github.com/smorinlabs/template-press/commit/7d77ca7480779ff2a56929de16950d8cab2561f6))
* **rebrand:** compile rendered substitution table ([8b63b36](https://github.com/smorinlabs/template-press/commit/8b63b361affe4f24f0145fc72cd549f4e4593b08))
* **rebrand:** compile substitution table ([54a1175](https://github.com/smorinlabs/template-press/commit/54a1175a0c9849f6be5e564a68a979989b0b68bc))
* **rebrand:** per-rule scan policy for regenerated outputs ([21cbede](https://github.com/smorinlabs/template-press/commit/21cbede490e77c5c3e7d4ff7ef0de8daa8814f6f))
* **rebrand:** per-rule scan policy for regenerated outputs; loud regen-failure reporting ([6428a9c](https://github.com/smorinlabs/template-press/commit/6428a9c65313944faed9e3a4e18367dfe0edb47a))
* **rebrand:** record active platform actions ([125436e](https://github.com/smorinlabs/template-press/commit/125436ee36cd2cf6533f35aade095a9420e777ea))
* **rebrand:** select platform-specific commands ([5e5ddf5](https://github.com/smorinlabs/template-press/commit/5e5ddf5843e160ead1a92c40d602f3f5c228d3a7))
* **rebrand:** support platform-conditional declared commands ([bd52085](https://github.com/smorinlabs/template-press/commit/bd520857daa967ad36780030a101418011e294c8))
* **rebrand:** thread selected rules through commands ([e72125f](https://github.com/smorinlabs/template-press/commit/e72125f25168c0c00c0749da488bfb69262328a4))


### Bug Fixes

* **rebrand:** address substitution table review ([da9a6f5](https://github.com/smorinlabs/template-press/commit/da9a6f5e3b013cb0b6fc96f341a7c3be679acbe3))
* **rebrand:** align pipeline validation surfaces ([5c4e40f](https://github.com/smorinlabs/template-press/commit/5c4e40fe89a7da0e023add24daff4cb4f3bcf789))
* **rebrand:** apply boundary matching inside the hunt, not as a post-filter ([2d7df54](https://github.com/smorinlabs/template-press/commit/2d7df54059d81cd8617ab3d6626a4b4a9804ddc6))
* **rebrand:** bracket conditional config inputs ([22b937e](https://github.com/smorinlabs/template-press/commit/22b937e94bae3b38173564a69c2e446da64ddb3c))
* **rebrand:** bracket git index capture ([09bbb98](https://github.com/smorinlabs/template-press/commit/09bbb986e2fe24a2f14145de285193104bb0a2be))
* **rebrand:** close final inventory review gaps ([d0e1992](https://github.com/smorinlabs/template-press/commit/d0e19923bb4cf9d56bd49049b7b54e785e42897c))
* **rebrand:** close final rename safety gaps ([623aa79](https://github.com/smorinlabs/template-press/commit/623aa79eba3538fb4888b6b434ef22ffdd8e3853))
* **rebrand:** close inventory race windows ([f00d9fa](https://github.com/smorinlabs/template-press/commit/f00d9fa78ac51fdff80d64f2e3941788c2a0d69c))
* **rebrand:** close inventory read races ([5a43710](https://github.com/smorinlabs/template-press/commit/5a43710303e7ebe9c37c07656173526274052448))
* **rebrand:** close inventory review gaps ([fe3fb2d](https://github.com/smorinlabs/template-press/commit/fe3fb2dc6a8250e6e2cf74dda6495fdb71edef13))
* **rebrand:** close substitution review gaps ([7d36746](https://github.com/smorinlabs/template-press/commit/7d36746626dd90145c4fe5fe16141c5e900dbc8c))
* **rebrand:** close surface review gaps ([46713ce](https://github.com/smorinlabs/template-press/commit/46713ce41bbb4d76371e15b1e6125d555f758436))
* **rebrand:** cover config and index visibility changes ([c3097d1](https://github.com/smorinlabs/template-press/commit/c3097d131c79ada6cb751ab989e03e6fb7356047))
* **rebrand:** detect symlink ancestors in virtual targets ([500d709](https://github.com/smorinlabs/template-press/commit/500d7095f46a30cbcff76c9c6c2e20c66168148a))
* **rebrand:** guard effective config transitions ([488bdeb](https://github.com/smorinlabs/template-press/commit/488bdeb8810701353a9e38818a0f5b77613c37a8))
* **rebrand:** guard missing config includes ([fe631cd](https://github.com/smorinlabs/template-press/commit/fe631cd8aadb5f931ee8048fc44a907cb1115974))
* **rebrand:** guard post-command git visibility ([8e40e16](https://github.com/smorinlabs/template-press/commit/8e40e1699215b776cc72d9000dd2eab9ac47dc9a))
* **rebrand:** handle unsupported atomic renames ([2c83968](https://github.com/smorinlabs/template-press/commit/2c83968aaa683ddec3561cacf3a419e9507f18ca))
* **rebrand:** harden shared inventory boundaries ([9a8c0c4](https://github.com/smorinlabs/template-press/commit/9a8c0c4d6de6d076a4e38cf4e409e7734e20ff77))
* **rebrand:** limit stability sinks to enabled forms ([a774eb3](https://github.com/smorinlabs/template-press/commit/a774eb33e3cadd8d718366bf18a7d38b3297bd86))
* **rebrand:** make inventory reads phase stable ([042f9df](https://github.com/smorinlabs/template-press/commit/042f9dffd9f155c2f6caf54b8b5ba46f740550c6))
* **rebrand:** make inventory tests portable ([10adbdb](https://github.com/smorinlabs/template-press/commit/10adbdbfb34bf70cf762d8d65b24cdf6a1a25275))
* **rebrand:** normalize marker inventory races ([498980f](https://github.com/smorinlabs/template-press/commit/498980f640aad18d98621e3b56d4b8031875fa64))
* **rebrand:** preserve gitlink boundaries on windows ([8cea374](https://github.com/smorinlabs/template-press/commit/8cea374566a3d9b406ed75d3d124fb61e19c7183))
* **rebrand:** preserve links when dangling target rename skips ([179d8f2](https://github.com/smorinlabs/template-press/commit/179d8f2751ceeb5df3a5d8ef677f3ff091e6b6af))
* **rebrand:** preserve links when dangling target rename skips ([c326a2e](https://github.com/smorinlabs/template-press/commit/c326a2ea6678edf2b3a1bc0c4ba9822941e9d4ff))
* **rebrand:** preserve pipeline matcher semantics ([0b7f76a](https://github.com/smorinlabs/template-press/commit/0b7f76ac9c131a580a02ab07efb20f44f5553c4c))
* **rebrand:** preserve read race refusals ([ccedcd5](https://github.com/smorinlabs/template-press/commit/ccedcd53eef777be737dafb19f78ddc47f7fb052))
* **rebrand:** preserve targets through symlink ancestors ([3901d52](https://github.com/smorinlabs/template-press/commit/3901d52939dae012c863d4f28ebc75b98671d201))
* **rebrand:** print skipped reasons on the regen-failure path ([64eea2d](https://github.com/smorinlabs/template-press/commit/64eea2d102df04aa150edf94dd350d8532f751c5))
* **rebrand:** refuse unscannable inputs before writes ([d4f3364](https://github.com/smorinlabs/template-press/commit/d4f336458fbda764ef303fdaf47d805f7bbf5f04))
* **rebrand:** reject converging target paths ([d423e96](https://github.com/smorinlabs/template-press/commit/d423e9663c0dadf8379e4b25a5ed2a61454a370e))
* **rebrand:** scan dirty gitlink replacements ([6f93052](https://github.com/smorinlabs/template-press/commit/6f93052782a16d44ea1ac85994d7a1e0b3460f95))
* **rebrand:** scope dangling ancestor suppression ([ecd891f](https://github.com/smorinlabs/template-press/commit/ecd891f02306472e84d53b1673723c30465b3b8e))
* **rebrand:** support git prefix includes ([e7d3c48](https://github.com/smorinlabs/template-press/commit/e7d3c48fa1323d33a9f615f889ea666a8aa52ea9))
* **rebrand:** support stable split indexes ([36ac30c](https://github.com/smorinlabs/template-press/commit/36ac30c1db2b6257abc06ef5f4e82d89184295b3))
* **rebrand:** track effective git config activation ([59b1ddc](https://github.com/smorinlabs/template-press/commit/59b1ddc60447a8c9ca6bf09661cd4fb9668bca28))
* **rebrand:** validate fallback read ancestors ([5fe4454](https://github.com/smorinlabs/template-press/commit/5fe4454a4aa08ec64aa7dda942d96caf987ad2ca))
* **rebrand:** validate reset visibility during planning ([21515a9](https://github.com/smorinlabs/template-press/commit/21515a9249defd31cbd7eca339ac32acdd7a0a2c))


### Refactor

* **rebrand:** centralize pipeline validation ([b737f29](https://github.com/smorinlabs/template-press/commit/b737f29c489ce3804b41dfd69ad3dc6a3681e5d0))
* **rebrand:** centralize pipeline validation ([1146c2c](https://github.com/smorinlabs/template-press/commit/1146c2c03482745128a50d107baf6a6cf62a0c7c))
* **rebrand:** centralize surface inventory ([84edeb4](https://github.com/smorinlabs/template-press/commit/84edeb4b8939298bee36b54e21346f091e722da2))

## [3.4.0](https://github.com/smorinlabs/template-press/compare/v3.3.0...v3.4.0) (2026-07-27)


### Features

* **rebrand:** add declared [[regenerate]] and [[reset]] config schemas ([759c56e](https://github.com/smorinlabs/template-press/commit/759c56e39d292d7cb34aef05ba6638a0e35f9801))
* **rebrand:** add press check-tools, the tool-availability verb ([2af2918](https://github.com/smorinlabs/template-press/commit/2af2918164930cbf41ddaabc48aa6de51a151deb))
* **rebrand:** apply declared resets at position zero ([cd4e635](https://github.com/smorinlabs/template-press/commit/cd4e6354bde58c1282eb1ececd3ac8c9bb1b7b53))
* **rebrand:** earn hermetic-verify exemption by cap and declaration ([7f0b4aa](https://github.com/smorinlabs/template-press/commit/7f0b4aa23eb0928c488a01744c9288a28f240f4a))
* **rebrand:** earn the scan exemption by result — postconditions + final pass ([5493fa7](https://github.com/smorinlabs/template-press/commit/5493fa7c3d3f3fe6ccbc29ba1b2c152d0851e06b))
* **rebrand:** execute declared commands via the generic executor ([608932d](https://github.com/smorinlabs/template-press/commit/608932dee591bcd5aa1cbff2b85335b277d0957e))
* **rebrand:** gate the press on the excluded-file contract ([1bdd284](https://github.com/smorinlabs/template-press/commit/1bdd2847c139c65725b810e32c4d7a2c0cc44135))
* **rebrand:** invalidate the prior receipt on a forced re-press ([467671e](https://github.com/smorinlabs/template-press/commit/467671efdde57ed373549f18fecc04b482acdc20))
* **rebrand:** migrate this repo to declared regenerate and reset rules ([5efa42e](https://github.com/smorinlabs/template-press/commit/5efa42ec17c1dfa5d6288a4ca1e9879b141c779a))
* **rebrand:** preflight reset targets with two-level preview ([de75784](https://github.com/smorinlabs/template-press/commit/de75784af2b161d750592a7a43a67f8f91e04b1f))
* **rebrand:** resolve declared commands at plan time; refuse stale argv ([e609ef9](https://github.com/smorinlabs/template-press/commit/e609ef9f5e6b710075b7cb5081c764ee4183b073))


### Bug Fixes

* **rebrand:** chain declared-path translation to a fixpoint ([1a62e81](https://github.com/smorinlabs/template-press/commit/1a62e8171ddbd262877a50df2bca72b71bd26ab1))
* **rebrand:** close three plan/postcondition gaps from re-review ([8410d00](https://github.com/smorinlabs/template-press/commit/8410d00fe32c3774866d3c2e880f9a63a7fad6a6))
* **rebrand:** expand display forms in changed-fields scan; load stubs pre-press in verify ([12898ec](https://github.com/smorinlabs/template-press/commit/12898eced368a0d365f4e3ed3b43108d88b55fe9))
* **rebrand:** final review pass — recovery containment, scan symmetry, guards ([cf4aef2](https://github.com/smorinlabs/template-press/commit/cf4aef23aa619be33bfee7af2ba043b6adaa4182))
* **rebrand:** model declared resets in hermetic verify ([94d5c84](https://github.com/smorinlabs/template-press/commit/94d5c843fe4e3ea1c924fdef6390e3fb561b33fd))
* **rebrand:** normalize check-tools config errors to exit 2 ([1073b87](https://github.com/smorinlabs/template-press/commit/1073b87de612145ec4810db2a73e02b650202004))
* **rebrand:** regenerate bun.lock from scratch via a declared script ([b2be402](https://github.com/smorinlabs/template-press/commit/b2be402e5830a4f7911b666fdcefe359a19aff6f))
* **rebrand:** reject terminal controls in declared paths ([bdd981e](https://github.com/smorinlabs/template-press/commit/bdd981e57dd816b2cbab634230b5a92eeb563064))
* **rebrand:** restore control files after declared-command failures ([a1d8461](https://github.com/smorinlabs/template-press/commit/a1d846170a586c53ea854ee4b76ffbf117986e69))
* **rebrand:** restore modes without following swapped symlinks ([05b163b](https://github.com/smorinlabs/template-press/commit/05b163bf5da34c566b1631c22fb3e125ff4a22b3))
* **rebrand:** tolerate non-utf-8 bytes from git and declared commands ([36cd867](https://github.com/smorinlabs/template-press/commit/36cd867fa573568a782a84a01b458efea759e8d6))

## [3.3.0](https://github.com/smorinlabs/template-press/compare/v3.2.0...v3.3.0) (2026-07-25)


### Features

* **cli:** fail loud on half-specified display_name ([e90404c](https://github.com/smorinlabs/template-press/commit/e90404c328495ad09f1aa4879891baced86c80a8))
* **engine:** display-name form pairs in rewrite and doctor scans ([89b867d](https://github.com/smorinlabs/template-press/commit/89b867dfe5ae90b80c4c15dea659a27b86d7b353))
* **engine:** exact replace rules run before the token pass ([34c65b2](https://github.com/smorinlabs/template-press/commit/34c65b255ea1843fb45cfd91b8ae8abd54925cc1))
* **engine:** opt-in per-field substring rewrite mode ([6165371](https://github.com/smorinlabs/template-press/commit/616537164e64101d3186ca5ce5e85124441d80fd))
* **engine:** replace rules and substring fields in path renames ([4e318c8](https://github.com/smorinlabs/template-press/commit/4e318c874e436a3952bc7c78b3d0d2b08aa59493))
* **identity:** optional display_name field with closed form set ([a6fa94c](https://github.com/smorinlabs/template-press/commit/a6fa94c091c28d0b6db172604892394d898d2676))
* **rebrand:** display_name field, replace rules, and substring mode (c/d/e gaps) ([a3317cb](https://github.com/smorinlabs/template-press/commit/a3317cb1150e01f48e712b87fd668f9a4655a0b5))
* **rules:** [[replace]] rules, substring and display-form knobs ([e19b7fc](https://github.com/smorinlabs/template-press/commit/e19b7fc11909de06a72303a50ce94e7755e898ae))
* **rules:** render replace patterns per identity and scope by glob ([52105a8](https://github.com/smorinlabs/template-press/commit/52105a8a3d7ece790a847affd5c1662301dee885))
* **synthesize:** deterministic synthetic display name ([961354a](https://github.com/smorinlabs/template-press/commit/961354ab470b94b6f64c313473fb2567c088461b))
* **verify:** scan display_name as its own field when declared ([6f925f3](https://github.com/smorinlabs/template-press/commit/6f925f390f394ec7c1d9ca3ecfd2ae90c9d243e8))


### Bug Fixes

* **cli:** collision preflight covers derived display forms ([1ebcbd0](https://github.com/smorinlabs/template-press/commit/1ebcbd0b89d31396bc4cc4cd05b46ee8347ebd18))
* **cli:** honor display_forms subset in the post-apply doctor scan ([d8993b6](https://github.com/smorinlabs/template-press/commit/d8993b6d62c61a9b25e3efadc6f29a24936a9251))
* **cli:** substring-aware collision preflight ([5c06173](https://github.com/smorinlabs/template-press/commit/5c06173588d5c84c5dc552b1d3b95967bd15460c))
* **config:** reject non-string identity values ([2117caa](https://github.com/smorinlabs/template-press/commit/2117caa7f845b9f09445aad6819eb1679cacd65c))
* **config:** validate identity table keys ([8e8292d](https://github.com/smorinlabs/template-press/commit/8e8292d79b79b980a8be6dbef5016b7402a9d2d0))
* **doctor:** display-form path scan and substring awareness ([3e60eed](https://github.com/smorinlabs/template-press/commit/3e60eed76e58a00dcdda9df19d31afca36492bd8))
* **doctor:** scan gitlink names for identity and rule literals ([c71dbe4](https://github.com/smorinlabs/template-press/commit/c71dbe438adee123b159255423cf59d1d01edb52))
* **doctor:** scan rendered replace-rule literals ([00a7ba8](https://github.com/smorinlabs/template-press/commit/00a7ba8e9be95d8be71c43b73536ac38297bfb5f))
* **doctor:** scope rule-literal scan against pre-rename paths ([9d9d0c5](https://github.com/smorinlabs/template-press/commit/9d9d0c53c3a9f105e95370d710e58c9630ba575b))
* **engine:** coalesce same-field display-form duplicates ([78cef0d](https://github.com/smorinlabs/template-press/commit/78cef0dec26fbe383a3a0da002b767bbc06b883a))
* **engine:** match path-rule scope against symlink targets ([ac6044c](https://github.com/smorinlabs/template-press/commit/ac6044c6ef06dbd37e4938ade4b79256f0244219))
* **engine:** reject ambiguous duplicate replacement sources ([23df539](https://github.com/smorinlabs/template-press/commit/23df5392c9951d305131adebf53faa670a23e259))
* **engine:** reject conflicting rendered rule sources ([6372ea5](https://github.com/smorinlabs/template-press/commit/6372ea5863cad1ba62ee7fa3f2f4cc899f10f939))
* **engine:** reject self-reapplying path rules and loud fixpoint exhaustion ([5786a13](https://github.com/smorinlabs/template-press/commit/5786a13d8bd23b342f9dba9cc5c66a5b0f84294a))
* **engine:** remove and recreate directory symlinks the Windows way ([61dffdb](https://github.com/smorinlabs/template-press/commit/61dffdb9d45bb14a057e6ef509461ed979631fe6))
* **engine:** rename and symlink hardening from adversarial review ([42f9206](https://github.com/smorinlabs/template-press/commit/42f92063ecf4e5864d054e5c286b90484c68a7e7))
* **engine:** rename symlink names via no-follow candidates ([33c0939](https://github.com/smorinlabs/template-press/commit/33c093922f26cd998cd5beeaad3148c43adb07fe))
* **engine:** retarget links only when their target actually moves ([a0f0f98](https://github.com/smorinlabs/template-press/commit/a0f0f985af5df5b7e5f2bff47d7f1e85773ad351))
* **engine:** structural path-component containment guards ([24b0636](https://github.com/smorinlabs/template-press/commit/24b0636579ea7b12a4820ac22cb313fa76c31434))
* **engine:** symlink and path-rule hardening from pr review ([af3b7cf](https://github.com/smorinlabs/template-press/commit/af3b7cf6aa959229fbba6fd0148346bdfa9eccf6))
* **engine:** validate rendered rule output against the token pass ([9d347d3](https://github.com/smorinlabs/template-press/commit/9d347d3e82849c0f60c0b84e14e2413c9780329d))
* **identity:** reject path dot segments in free-form fields ([82f7925](https://github.com/smorinlabs/template-press/commit/82f7925b288e7bcc3c088d43390ed514a6dadcac))
* **rules:** close fail-open parser gaps ([32bd4b2](https://github.com/smorinlabs/template-press/commit/32bd4b21157afb0c9e10a9cc8983bae8cd7bdb1b))
* **rules:** fail closed on unknown [rules] keys ([fe2076b](https://github.com/smorinlabs/template-press/commit/fe2076bb12b161f9d2f650cad6c8d0cb1986bd6b))
* **rules:** reject rule static text overlapping changed tokens ([7e3fb8f](https://github.com/smorinlabs/template-press/commit/7e3fb8f647584d39cb272361de86ad842aa2bab8))
* **rules:** use fnmatchcase for platform-deterministic glob matching ([3793e25](https://github.com/smorinlabs/template-press/commit/3793e257423d0e85c484376c689007695cef1e2b))
* **synthesize:** letters-only synthetic display words ([394f448](https://github.com/smorinlabs/template-press/commit/394f448c6c835bb14236505d45e5e97ef4fceb65))
* **verify:** require declared display_name to occur in the target ([bc3dc05](https://github.com/smorinlabs/template-press/commit/bc3dc058e0b9a29a17f1aadc68f98114fc0debb5))
* **verify:** scan rendered rule literals in the hermetic scan ([bebc9bd](https://github.com/smorinlabs/template-press/commit/bebc9bd376ad4098bac90493d6f8cede4d8184b9))
* **verify:** scan substring rewrite fields as fields ([504e3ee](https://github.com/smorinlabs/template-press/commit/504e3ee053d9090db588256c067666855b15514e))
* **verify:** union substring rewrite fields into the hermetic scan ([0ea5c98](https://github.com/smorinlabs/template-press/commit/0ea5c98b2211ba5108cb41beecd7a46788625a0e))

## [3.2.0](https://github.com/smorinlabs/template-press/compare/v3.1.0...v3.2.0) (2026-07-20)


### Features

* **verify:** press verify — hermetic self-press leak check ([#38](https://github.com/smorinlabs/template-press/issues/38)) ([d7e5c9d](https://github.com/smorinlabs/template-press/commit/d7e5c9d08eb894395803e7defbe6c7d179d86440))

## [3.1.0](https://github.com/smorinlabs/template-press/compare/v3.0.0...v3.1.0) (2026-07-17)


### Features

* guard press/ dir-name collision with content-keyed exemption ([#30](https://github.com/smorinlabs/template-press/issues/30)) ([ca213cf](https://github.com/smorinlabs/template-press/commit/ca213cf570ad356893c84511de7949813ee101bf))

## [3.0.0](https://github.com/smorinlabs/template-press/compare/v2.1.1...v3.0.0) (2026-07-17)


### ⚠ BREAKING CHANGES

* per-target control files moved from .press/{source,rules,receipt}.toml to press/press-{source,rules,receipt}.toml; the tool recognizes only the new names (no fallback). Targets pressed under .press/ must rename or remove that directory.

### Features

* external-target rebrand press (clean-core rebuild m0-m3) ([#15](https://github.com/smorinlabs/template-press/issues/15)) ([560360a](https://github.com/smorinlabs/template-press/commit/560360a67087e1098e9df94c5912fc2286b4b526))
* rename press control dir to press/ with press- prefix ([#27](https://github.com/smorinlabs/template-press/issues/27)) ([1be6a40](https://github.com/smorinlabs/template-press/commit/1be6a4037ea85c90a9888ef94b6a274acfd5575e))


### Bug Fixes

* post-merge sweep — identity validation, verification integrity, cve bumps ([#17](https://github.com/smorinlabs/template-press/issues/17)) ([c7ee2c4](https://github.com/smorinlabs/template-press/commit/c7ee2c4d87d537ebeab3c1b9c9e8fc2f8a609625))


### Refactor

* shed blueprint residue — pure publishable rebrand utility (M4) ([#18](https://github.com/smorinlabs/template-press/issues/18)) ([81ca3fb](https://github.com/smorinlabs/template-press/commit/81ca3fb2318a8d03afa18572e4a59c0d519d8287))

## Changelog
