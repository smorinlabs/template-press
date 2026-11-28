# Changelog

## [5.0.1](https://github.com/smorinlabs/template-press/compare/v5.0.0...v5.0.1) (2026-11-28)


### Bug Fixes

* **rebrand:** clean translated source dir and guard git visibility and untracked files ([ab9c2f2](https://github.com/smorinlabs/template-press/commit/ab9c2f21dc7408a8c8c804110b9ef7e25e63fd02))
* **rebrand:** handle crlf line endings and windows paths cleanly ([b2110b3](https://github.com/smorinlabs/template-press/commit/b2110b37409daccb05c8b2e55a9b73c442d3f63f))
* **rebrand:** harden regenerate dir preflight, exemptions, and multiline replace ([38d200e](https://github.com/smorinlabs/template-press/commit/38d200e4bdf0168f350d8b264cd4603d3b4e21d6))
* **rebrand:** recheck ignore fingerprints before caching directory ignores ([df0ad0e](https://github.com/smorinlabs/template-press/commit/df0ad0e7e324493361b6cabd4a7c97885283e94b))
* **rebrand:** refuse cargo target renames leaving multiple candidate files ([6950ede](https://github.com/smorinlabs/template-press/commit/6950ede36e18ecd7d0d5efe645bc017ff54ed527))
* **rebrand:** run exit-2 plan gates before exit-1 keep-name preflight ([2e677c6](https://github.com/smorinlabs/template-press/commit/2e677c6273103c97742a08ee60ed13577cc24ef5))


### Performance Improvements

* **ci:** benchmark worksteal on windows and strip sample hooks ([c93ec8f](https://github.com/smorinlabs/template-press/commit/c93ec8f69b4e90ef05e3a08f6a15fd993b23b65f))
* **ci:** speed up Windows CI via cached fixture repos, lean test group, and worksteal ([66450a8](https://github.com/smorinlabs/template-press/commit/66450a8cb785152ddfb1afe504a38f53275b7413))
* **rebrand:** cut git spawns, double sandboxing, and scan overhead ([f91ea00](https://github.com/smorinlabs/template-press/commit/f91ea005138f69b161c2710fa57bf4eb46f73be9))
* **rebrand:** fast-path kept_spans and update matrix fixtures for decision 1 ([e296327](https://github.com/smorinlabs/template-press/commit/e2963272eb351e9b6069f1588bec17dd84b290c5))
* **rebrand:** speed up directory history validation ([2b86237](https://github.com/smorinlabs/template-press/commit/2b8623776ca03b0bf2e4e894871bbb7f6e090631))
* speed up rebrand engine, test matrix, and CI checks ([987495d](https://github.com/smorinlabs/template-press/commit/987495d63aa7bd971e6113bacf4fce2ec3dd008f))
* **tests:** cache pre-committed fixture repos and add lean test group ([3cbbc55](https://github.com/smorinlabs/template-press/commit/3cbbc550bf0596c9db28f87d2f61c7a9346583b1))
* **tests:** parallelize cargo matrix and reuse empty git templates ([c81388d](https://github.com/smorinlabs/template-press/commit/c81388d63bd75c2d00a6ef05791ff7240d6f3594))
* **tests:** reuse empty git template in remaining rebrand tests ([aee81a6](https://github.com/smorinlabs/template-press/commit/aee81a69b7b2d291313ac708e5d4161aa8a56d7b))

## [5.0.0](https://github.com/smorinlabs/template-press/compare/v4.1.0...v5.0.0) (2026-11-25)


### ⚠ BREAKING CHANGES

* **rebrand:** targets with more than one language manifest must add languages = [...] under [rules] in press/press-rules.toml.

### Features

* **ci:** restore contributors-please automation ([169e646](https://github.com/smorinlabs/template-press/commit/169e6468ad6024f53014c6942e9b45db90b1b435))
* **ci:** restore contributors-please automation ([8208f76](https://github.com/smorinlabs/template-press/commit/8208f767968acffb585417af8f226a448bc9f3ad))
* **discovery:** propose source config from package.json ([e368e76](https://github.com/smorinlabs/template-press/commit/e368e76b47bba207fd17d1e87ffb440b25c4bc19))
* **discovery:** read identity from package.json ([6733b69](https://github.com/smorinlabs/template-press/commit/6733b69dd4bd04c8e26ccd42114660e21ab966f0))
* **identity:** add optional npm and cli name fields ([db63383](https://github.com/smorinlabs/template-press/commit/db63383bd27af615aea7e470dd73a7cc234ced49))
* **rebrand:** accept leading underscores in cargo_names values ([3afdf3c](https://github.com/smorinlabs/template-press/commit/3afdf3c71beb4c5d0a92567a9e22bed85e42852f))
* **rebrand:** add [[cargo_split]] for one-press hyphen-free crate renames ([4ab3a79](https://github.com/smorinlabs/template-press/commit/4ab3a793a0cff10966c4baebf933eb7b90958350))
* **rebrand:** add cargo_names identity table ([02af7bd](https://github.com/smorinlabs/template-press/commit/02af7bd03164446288ddd27ed9ee5be95c69f0e8))
* **rebrand:** cargo role placeholders in replace rules ([f5b44df](https://github.com/smorinlabs/template-press/commit/f5b44dfb6af837c0b364be6f2a5149bc068c14ae))
* **rebrand:** check manifests for declared target languages ([23a3740](https://github.com/smorinlabs/template-press/commit/23a37407d2df4d664e540fcd99f6724bd82d5308))
* **rebrand:** cross-check cargo names against manifests ([c97a91f](https://github.com/smorinlabs/template-press/commit/c97a91f5d894cfc1f7e4f89a8e757b16316b0370))
* **rebrand:** detect target languages from root manifests ([db18ae6](https://github.com/smorinlabs/template-press/commit/db18ae613de13234171f1839cb7ff00e95ec652a))
* **rebrand:** parse declared target languages ([ffa9161](https://github.com/smorinlabs/template-press/commit/ffa91613c783f9c424d3b17374b63851054a4c3d))
* **rebrand:** read cargo manifest identity facts ([309efdd](https://github.com/smorinlabs/template-press/commit/309efdd238d9f91bd960a368eab57906a884dfca))
* **rebrand:** require declared languages for multi-language targets ([2889bbf](https://github.com/smorinlabs/template-press/commit/2889bbf921897cc4b191499bd9265386defd80cb))
* **rebrand:** rewrite both spellings of cargo names ([af723d7](https://github.com/smorinlabs/template-press/commit/af723d7cee125ec482dab12b8bb26f4fcc5cf15a))
* **rebrand:** rewrite exact npm and cli names ([1222c6e](https://github.com/smorinlabs/template-press/commit/1222c6e34a297efb67e0f4078681b9bdf5108404))
* **rebrand:** support declared cargo lock regeneration ([b43edb6](https://github.com/smorinlabs/template-press/commit/b43edb699023bba9e07ef72d84def5663197b9b7))
* **rebrand:** support rust and cargo targets ([04769b2](https://github.com/smorinlabs/template-press/commit/04769b24b7b5665d8932cac3a6c1ac876b8a98bb))
* **rebrand:** support typescript and bun targets ([28165f0](https://github.com/smorinlabs/template-press/commit/28165f0c66d1a73fea4ebec4253a04b2a9c52608))
* **rebrand:** verify cargo names independently ([a8eb7e2](https://github.com/smorinlabs/template-press/commit/a8eb7e2953fb106d5267da6923ffdf2f53a0b4da))
* **regen:** exempt declared npm and pnpm lockfiles ([4e5bab5](https://github.com/smorinlabs/template-press/commit/4e5bab505d0363a92cb2662ebe9379f0962d023c))
* **rules:** protect declared keep names from rewrites ([e09ea19](https://github.com/smorinlabs/template-press/commit/e09ea195758c93d5c5678d9bee8f15d3cbd6f005))
* **verify:** honor keep names across every scan ([d1259e8](https://github.com/smorinlabs/template-press/commit/d1259e8d73de55b25aa61df175f502583a5e9dda))


### Bug Fixes

* escape unprintable paths in the coverage warning ([398e01b](https://github.com/smorinlabs/template-press/commit/398e01b2a852a17ce80b0fdd9f46e172a7315d04)), closes [#150](https://github.com/smorinlabs/template-press/issues/150)
* **hooks:** scan a branch's first push for secrets ([ebb4795](https://github.com/smorinlabs/template-press/commit/ebb4795703b6bba641b2cde16afb33f50400ece1))
* **hooks:** scan a branch's first push for secrets ([01a8796](https://github.com/smorinlabs/template-press/commit/01a8796c36e1e57ac51fc89fce7373d22c12e153))
* limit manifest override to the project name ([b08a661](https://github.com/smorinlabs/template-press/commit/b08a661b33f043d8d60a50074b4b74bcd6692e30))
* list the affected paths in the removal coverage warning ([c64e2e4](https://github.com/smorinlabs/template-press/commit/c64e2e4e370a035e56af6c4eb3b33bc1abb20404))
* list the affected paths in the removal coverage warning ([56328cd](https://github.com/smorinlabs/template-press/commit/56328cdc84078a4d53ab0b0d87e4fb3e51f7080a)), closes [#150](https://github.com/smorinlabs/template-press/issues/150)
* **projects:** p17 glyph-matches-state — track the pr merge as p17-t04 ([bb134ed](https://github.com/smorinlabs/template-press/commit/bb134edb7dbfb3bc58486e4bc3f29d313b4550b5))
* **projects:** p17 references-block — add the references block ([4b9de4e](https://github.com/smorinlabs/template-press/commit/4b9de4e19e4682ea610dc6bbbdef6234d8fa4a35))
* **projects:** p17 trunk-row-link-format — use the list row format ([b25b5a8](https://github.com/smorinlabs/template-press/commit/b25b5a816906bc7f382a810142872a7218614cd3))
* **rebrand:** align cargo gates across press and verify ([ae12509](https://github.com/smorinlabs/template-press/commit/ae125097d099525618f68adc9c22847ee9f6de51))
* **rebrand:** allow keep names with edge separators ([bf209ca](https://github.com/smorinlabs/template-press/commit/bf209ca23d581f8f9b9514c95a66f66ed52ade2d))
* **rebrand:** allow whitespace before the bang of an include macro ([e4bc46d](https://github.com/smorinlabs/template-press/commit/e4bc46dcfd5d027bba58f49cd79b55509ddc424a))
* **rebrand:** apply split string rules only in compiled doctest blocks ([aa50144](https://github.com/smorinlabs/template-press/commit/aa501443f5ced5834231b85d26189dd5511b47f5))
* **rebrand:** carry kept spans and honor declared manifests ([ea59985](https://github.com/smorinlabs/template-press/commit/ea599859391dbb18282b28f9995329f5dd7296c6))
* **rebrand:** clarify and reuse control-directory advice ([ee30a76](https://github.com/smorinlabs/template-press/commit/ee30a763d26ec81a95dccbe6b42ee516dcc6966c))
* **rebrand:** clarify directory reuse and avoid duplicate inventory ([405a80f](https://github.com/smorinlabs/template-press/commit/405a80f278c699b6d4d3504da011e78f9922b361))
* **rebrand:** close a markdown fence only below four spaces of indent ([3e4f092](https://github.com/smorinlabs/template-press/commit/3e4f092e1f5f74e5c1d5ea30c9e81bd53d833ff6))
* **rebrand:** close ascii boundary and interleaved keep_names gaps ([661b0b6](https://github.com/smorinlabs/template-press/commit/661b0b6a9a584dcfde495c5308d9cbca9f2eab4c))
* **rebrand:** close cargo verify and refusal gaps ([b4832e9](https://github.com/smorinlabs/template-press/commit/b4832e9888cd44ac4e0302cff7ac4c2216531310))
* **rebrand:** close three more ways a doc string can be misread ([334d3e9](https://github.com/smorinlabs/template-press/commit/334d3e93680a77ef1d3cea0a777a2b7ce15c244b))
* **rebrand:** count a stringify or concat rename only in a use item ([87a36fa](https://github.com/smorinlabs/template-press/commit/87a36fa6d8ce90f8ce0a9ebb114727bc937e8587))
* **rebrand:** cross-check a symlinked path dependency inside the tree at its real path ([b3339d1](https://github.com/smorinlabs/template-press/commit/b3339d145968f7d6c83545c62fd2f4cd64a23ba2))
* **rebrand:** detect scoped npm names across path components ([4b79f44](https://github.com/smorinlabs/template-press/commit/4b79f44032c2bd379cde78bc16d829a24a02ad88))
* **rebrand:** exempt only names a press row rewrites ([a42ec71](https://github.com/smorinlabs/template-press/commit/a42ec71d14591720002b55c39688ebdd49d09a6f))
* **rebrand:** find a module file beside a root-level rust file ([ded2ad2](https://github.com/smorinlabs/template-press/commit/ded2ad2afeee5178080c20bbd812bb86eed6263e))
* **rebrand:** follow a stringify or concat call across the item's doc text ([c8e5e18](https://github.com/smorinlabs/template-press/commit/c8e5e18664478c8f211596cd353cccac5f1807d3))
* **rebrand:** harden language guard after final review ([6cdb01f](https://github.com/smorinlabs/template-press/commit/6cdb01fcc91abced53643910611023220f77e62f))
* **rebrand:** honor cargo auto-discovery flags in the compiled-file walk ([70766b8](https://github.com/smorinlabs/template-press/commit/70766b8bbbd0c3dd5337f952cdd2376e55a38696))
* **rebrand:** judge cargo paths that manifests declare ([1071060](https://github.com/smorinlabs/template-press/commit/107106065553e3822206716a14268d4741920823))
* **rebrand:** judge name-inferred and workspace cargo paths ([a3add3d](https://github.com/smorinlabs/template-press/commit/a3add3d5453baa07fd4b5ecc653311a8f84a8413))
* **rebrand:** judge only compiled rust files and follow inline and cfg_attr module paths ([992331a](https://github.com/smorinlabs/template-press/commit/992331af03205a3b8551b34a2e5e541b7c0aefc5))
* **rebrand:** judge unmapped crates by their rewrites ([c7abeb6](https://github.com/smorinlabs/template-press/commit/c7abeb6896e076cf63417e6f28c7151342f80296))
* **rebrand:** keep a failing verify result when copy cleanup fails ([67168d5](https://github.com/smorinlabs/template-press/commit/67168d5f8dfbd69720d9e61bc21054bccc8f856f))
* **rebrand:** keep one rules selection per press ([027cfeb](https://github.com/smorinlabs/template-press/commit/027cfeb895669f555b163f024517bcb5341119ed))
* **rebrand:** keep the name-based check for a module under a cfg_attr path ([377a947](https://github.com/smorinlabs/template-press/commit/377a9470ef79bd5862168c88e0d3300742853bc1))
* **rebrand:** leave a childless inline path override to its children ([d2dac84](https://github.com/smorinlabs/template-press/commit/d2dac84bf8baa80a591c2d7cf90b7ffe52c2ad24))
* **rebrand:** let a private-copy setup failure keep the press ([7bd3e12](https://github.com/smorinlabs/template-press/commit/7bd3e1215ef16de2d3f78450e26ba5a4239ec928))
* **rebrand:** lex doc-comment strings and require cfg and real comparisons ([bed439c](https://github.com/smorinlabs/template-press/commit/bed439cf27be3da34f6246b795d65fa79979a07d))
* **rebrand:** name the exclusion when a binary token sits in an excluded file ([a3cc898](https://github.com/smorinlabs/template-press/commit/a3cc898d20b757b0dd029a0842272dd25ce0d25a))
* **rebrand:** name the pnpm exclude in its suggestion ([48afc45](https://github.com/smorinlabs/template-press/commit/48afc45587834fe2dcd7fb2344f50a44a7c33614))
* **rebrand:** narrow the cargo identifier gate ([2caea59](https://github.com/smorinlabs/template-press/commit/2caea5978384dffd682a78175710fb5fbb3899ce))
* **rebrand:** offer both language choices in the guard refusal ([38b61e4](https://github.com/smorinlabs/template-press/commit/38b61e4be9604248642a6556a667781e8fb72cd6))
* **rebrand:** open no markdown fence on a backtick info string with a backtick ([bc78cea](https://github.com/smorinlabs/template-press/commit/bc78cea846baa602d63d3ba24fd13331b8335960))
* **rebrand:** parse package.json author in linear time ([ad0b923](https://github.com/smorinlabs/template-press/commit/ad0b9232ac4218d3e3806606ce7ebdb1adbfa88a))
* **rebrand:** press a path dependency reached through a symlinked directory ([916a1f0](https://github.com/smorinlabs/template-press/commit/916a1f026ac090effcd9b0c46e11914ea56f7db1))
* **rebrand:** propose cli_name only from an object-form bin key ([07faf26](https://github.com/smorinlabs/template-press/commit/07faf265858111b125190d24cd5379a066ee6881))
* **rebrand:** propose only object-form bins as cli name ([e206694](https://github.com/smorinlabs/template-press/commit/e206694b126686e558e04d72789970cbb39eb2d1))
* **rebrand:** prove a CARGO_PKG_NAME comparison only between bare operands ([c8f9b7f](https://github.com/smorinlabs/template-press/commit/c8f9b7f7c712e1218da4e735f8e6f3f2700a00c7))
* **rebrand:** read a doc-included readme fence in a block quote as code ([2018622](https://github.com/smorinlabs/template-press/commit/20186229cc45e753fcb3c6202f19e77523c649a0))
* **rebrand:** read an inner doc comment after unread doc text in each open state ([53c4e49](https://github.com/smorinlabs/template-press/commit/53c4e4910a267c878b0faae67239ea2bbf3c0217))
* **rebrand:** read doc comments as code unless rustdoc provably skips them ([a20a5ad](https://github.com/smorinlabs/template-press/commit/a20a5adc0b959600ebc22da33a2eecfba743bf12))
* **rebrand:** read hex and underscored unicode escapes in char literals ([7fcd98d](https://github.com/smorinlabs/template-press/commit/7fcd98db67ee59e22f7cb6176b29928db2847743))
* **rebrand:** read include checks past comments and whitespace in rust sources ([c1cef8e](https://github.com/smorinlabs/template-press/commit/c1cef8e19a36fd8586a64febcd5cee5c121fe4d6))
* **rebrand:** read include macros written with brackets or braces ([1ccb660](https://github.com/smorinlabs/template-press/commit/1ccb660eca521d7ef781859793707168b5560880))
* **rebrand:** read the legacy underscore cargo dependency tables ([e1e9f84](https://github.com/smorinlabs/template-press/commit/e1e9f84825502a13a1f1af9d8d52cb731a8b1900))
* **rebrand:** refuse a char literal of the crate name in a split press ([007570e](https://github.com/smorinlabs/template-press/commit/007570e3862e9e48006a2062b4a2399f38d36fa7))
* **rebrand:** refuse a content row that splits a path rust source declares ([1a96d36](https://github.com/smorinlabs/template-press/commit/1a96d36b9116712e2498069d2f722840d7674c4c))
* **rebrand:** refuse a destination crate name that is a rust keyword ([bb89a90](https://github.com/smorinlabs/template-press/commit/bb89a90718b281ceacb60f16ebb92ad4f2e6729e))
* **rebrand:** refuse a doctest char literal of the crate name in a split press ([2185756](https://github.com/smorinlabs/template-press/commit/2185756d494ccb8a9129ef8f841de92d05a87281))
* **rebrand:** refuse a hyphenated cargo name from a replace rule in rust files ([ec96521](https://github.com/smorinlabs/template-press/commit/ec965214a73a1e936f6d5f68c9cb41ca7fdfde60))
* **rebrand:** refuse a hyphenated crate declared only by its underscore form ([9f43f4f](https://github.com/smorinlabs/template-press/commit/9f43f4f43d47272a864913e308e1bc14f5fb14be))
* **rebrand:** refuse a keyword crate name that a rename produces ([2543506](https://github.com/smorinlabs/template-press/commit/254350657fb52f440c338477eddc8ef8658d9335))
* **rebrand:** refuse a renamed stringify or concat in a split press ([453d755](https://github.com/smorinlabs/template-press/commit/453d755c41e2c31ea8d0c308bce1b903eebbd2a2))
* **rebrand:** refuse a rewrite that splits a crate from its path ([d7f312d](https://github.com/smorinlabs/template-press/commit/d7f312d32da578519a13737813a904425438b00b))
* **rebrand:** refuse a split crate name that is a literal's prefix ([8f94960](https://github.com/smorinlabs/template-press/commit/8f94960bc06e9f5097f04a370c9d652d2829ba9c))
* **rebrand:** refuse dependencies extending a declared name ([8695943](https://github.com/smorinlabs/template-press/commit/8695943f86c240a04920df7de7b8327f70b3379d))
* **rebrand:** refuse doc comments that follow doc text the press cannot read ([667d836](https://github.com/smorinlabs/template-press/commit/667d8366107e81a341c92874f5ac52af64afb439))
* **rebrand:** refuse glued text on multi-part names ([32d6dad](https://github.com/smorinlabs/template-press/commit/32d6dade1eb52c94c5d84f0489f12c3eb97a7c43))
* **rebrand:** refuse keep_names holding a complete source name ([ca6be85](https://github.com/smorinlabs/template-press/commit/ca6be85064ea060c70fb7d9b2e1e0a8202389e50))
* **rebrand:** refuse keep_names that wrap an identity in punctuation ([76ce9e6](https://github.com/smorinlabs/template-press/commit/76ce9e6e28d8525371fdccdd9c178550abc6b00c))
* **rebrand:** refuse keep_names wrapping an identity in slash or at ([7d60d85](https://github.com/smorinlabs/template-press/commit/7d60d853afffab4eb9eb17db8581b819296f0aa7))
* **rebrand:** refuse parent moves that change a kept path ([61b5bab](https://github.com/smorinlabs/template-press/commit/61b5bab02c74e9b564526942f63982f17ca0437d))
* **rebrand:** refuse single-token names touching a bare separator ([c1f235b](https://github.com/smorinlabs/template-press/commit/c1f235b920c8531ddab5fef97e1011d1d6a917d5))
* **rebrand:** refuse the package spelling in a readme that rustdoc compiles ([2319ca3](https://github.com/smorinlabs/template-press/commit/2319ca3ccdb21f6e1988437ffce8abf20a8e9512))
* **rebrand:** refuse uncovered bins and glued false siblings ([adf8058](https://github.com/smorinlabs/template-press/commit/adf805836ca9eac3a088bbf2ab2740cf57c6c27e))
* **rebrand:** refuse unprovable cargo_split spellings in rust strings and paths ([a9036dc](https://github.com/smorinlabs/template-press/commit/a9036dca2de2b2f62e394994509f7d2b1ccdd8d5))
* **rebrand:** resolve rust paths inside inline modules from their directory ([93849d3](https://github.com/smorinlabs/template-press/commit/93849d3da758cbaa57c3a7dcf3b23348247f548c))
* **rebrand:** scope recovery cleanup hints to the target ([34c692a](https://github.com/smorinlabs/template-press/commit/34c692aa6ef6726faafc6d351d2abcf4e4bfbff2))
* **rebrand:** see a spaced macro bang and refuse names in stringify and concat ([770db53](https://github.com/smorinlabs/template-press/commit/770db53251ff6e00c8c9b34a23be92a4684510d1))
* **rebrand:** seed build.rs and crate roots only where cargo builds them ([466ebe9](https://github.com/smorinlabs/template-press/commit/466ebe96faa7b69bf8185221021ba7081309ff23))
* **rebrand:** skip conventional roots that cargo does not select ([b831949](https://github.com/smorinlabs/template-press/commit/b8319496482a80ff595419f37ea9260fd6c41be8))
* **rebrand:** skip default crate roots that cargo does not compile ([59dae81](https://github.com/smorinlabs/template-press/commit/59dae813baf8a2357a4366cc94daf4413cc98501))
* **rebrand:** strip keep_names punctuation in linear time ([9ca704b](https://github.com/smorinlabs/template-press/commit/9ca704bf10145894245444adeea2f311db0a1d18))
* **rebrand:** suggest a bun regeneration that rewrites the lock identity ([43bb0d8](https://github.com/smorinlabs/template-press/commit/43bb0d8a6063f361a9c719f76ed5c80b49ebf462))
* **rebrand:** treat a scoped basename as a sibling name ([31bccca](https://github.com/smorinlabs/template-press/commit/31bccca051e8a269ba4030dbc6597f43edb1e30d))
* **rebrand:** treat camel case tails as sibling names ([9ee4f29](https://github.com/smorinlabs/template-press/commit/9ee4f295efcf930e6320b7b1b345f7e8a0f67b9b))
* **rebrand:** walk only the include edges and path modules rustc compiles ([fe50c24](https://github.com/smorinlabs/template-press/commit/fe50c24e5f7f01f55389f1ecdb5f48b2a742a1ac))
* **rebrand:** warn when reusing ignored root directories ([7785ab2](https://github.com/smorinlabs/template-press/commit/7785ab2b715f09da2d28de69d7375f90d3e9c4ae))
* **rebrand:** withhold the receipt when press verify would fail ([690c202](https://github.com/smorinlabs/template-press/commit/690c202c4ccc13f12b7fac8bb546c7b334d05d93))
* **rebrand:** withhold the receipt when press verify would fail ([8c0d848](https://github.com/smorinlabs/template-press/commit/8c0d8481b5004fd137aa3d0f49dc1964c57c7b6b))
* **rebrand:** word the cargo binary token refusal by direction ([5d3779e](https://github.com/smorinlabs/template-press/commit/5d3779e52f1d38a996a1880a1fe1b599fca61f8b))
* stop false receipts for hyphenated package names ([20ec28f](https://github.com/smorinlabs/template-press/commit/20ec28fb1f3769ea8050007a40d703ccfd833aa3))
* stop false receipts for hyphenated package names ([fa949a8](https://github.com/smorinlabs/template-press/commit/fa949a8ae82b59fb47e6d8e2df6e90b1fda5a674))
* **verify:** accept npm_name and cli_name scan fields ([bfd53c5](https://github.com/smorinlabs/template-press/commit/bfd53c566d504e065cf875378f33836f3623bc72))


### Performance Improvements

* **just:** run static checks before tests ([0724096](https://github.com/smorinlabs/template-press/commit/072409658750fded5faf671ec9153499f0d9413f))
* **matrix:** run live acceptance tests in parallel ([643ff5a](https://github.com/smorinlabs/template-press/commit/643ff5ae0b3a65b43a65bd44cdcbbe2e306fc465))
* **rebrand:** batch repository path lookups in capture ([2ab0408](https://github.com/smorinlabs/template-press/commit/2ab0408d8424364db2215b26721170bc4c9de0f5))
* run just check tests in parallel ([a87ef59](https://github.com/smorinlabs/template-press/commit/a87ef596f457336da81ac7f9fdc53c92e1a8adbb))


### Refactor

* **rebrand:** share compiled rows with the keep-name preflight ([ea1da38](https://github.com/smorinlabs/template-press/commit/ea1da38b4aee5f7781f9ac07b7d17d4384b40be2))

## [4.1.0](https://github.com/smorinlabs/template-press/compare/v4.0.1...v4.1.0) (2026-09-10)


### Features

* add press clean with declared cleanup paths ([3f8c9fa](https://github.com/smorinlabs/template-press/commit/3f8c9fa8adc34aad8dc7dc7c776660070ad93c43))
* **clean:** render declared clean paths and build the git clean argv ([e7adde3](https://github.com/smorinlabs/template-press/commit/e7adde3dd9bfa259e324fc1c07dafc3d467444f1))
* **clean:** report clean rules in check-tools and record them in the receipt ([d3d05c7](https://github.com/smorinlabs/template-press/commit/d3d05c7db667a3cb93c6de11bcf9294579097c33))
* **cli:** press clean — declared, git clean -X based pre-press cleanup ([756f0c3](https://github.com/smorinlabs/template-press/commit/756f0c36f3a8c9379bd4a9a9bb657d1b2d016b2e))
* **cli:** remedy argv and --diagnostics-json for closure refusals ([0c43f88](https://github.com/smorinlabs/template-press/commit/0c43f886d6913ad7b77291c0a3361cb81af4ebd3))
* closure diagnostics, removal coverage warnings, verify hints (P12 part 1) ([93ea576](https://github.com/smorinlabs/template-press/commit/93ea576dc123600daf05f2851bd8d6085ac22baf))
* declared in-place edit mechanism ([[edit]]) (P09) ([f8b74a4](https://github.com/smorinlabs/template-press/commit/f8b74a4554c7227d056c11a360f3cb614185341c))
* **edit:** execute declared in-place edits before regenerations; gate snapshots on any command ([8af957c](https://github.com/smorinlabs/template-press/commit/8af957c85fd936fd5150de900996e54a93532c25))
* **edit:** pin self-press version mirrors ([0ae5c9d](https://github.com/smorinlabs/template-press/commit/0ae5c9d5b860bf8479f8030c912dcf2cad272ce6))
* **guard:** --accept-origin-mismatch with per-field warning and receipt row ([05a74d5](https://github.com/smorinlabs/template-press/commit/05a74d50eb4db0f82be2f97ca4827e9e3861e035))
* **guard:** accept an origin that already names the destination ([da770c6](https://github.com/smorinlabs/template-press/commit/da770c61dcde4df220a1e7580cebc487c50bf2be))
* **guard:** origin relaxation (P12 part 2) ([421f073](https://github.com/smorinlabs/template-press/commit/421f073834ba5c8dd375c17d04869d3679e28fd5))
* **plan:** render and preflight [[edit]] commands ([a34730c](https://github.com/smorinlabs/template-press/commit/a34730cb2cbd84e6096484338d19597c65782433))
* **plan:** warn on rewritten directories with no declared removal; show removal counts ([a417b47](https://github.com/smorinlabs/template-press/commit/a417b479642b4114f225eaf90caf59949cd38a77))
* **plan:** warn when a source value occurs only as a prefix of a longer token ([e90b3bf](https://github.com/smorinlabs/template-press/commit/e90b3bf16d6ae1ef62a1a2b7f1984f62e28aca3f))
* **remove:** add frozen directory removal plans and history ([6079a22](https://github.com/smorinlabs/template-press/commit/6079a22b3fb3069b965ee1061765bc67a95349b4))
* **remove:** execute frozen members and record complete history ([f4d68e6](https://github.com/smorinlabs/template-press/commit/f4d68e603e003f65e4b121fbff58464968564921))
* **remove:** freeze declared directory members and safety checks ([db0a692](https://github.com/smorinlabs/template-press/commit/db0a69260ff213d3e428ae50d121c42b01c7d68b))
* **remove:** integrate directory history with press and verify ([175a28a](https://github.com/smorinlabs/template-press/commit/175a28a7d97e4f1d17a3bf361393eb92a5927abf))
* **remove:** migrate native research cleanup to directory rules ([23baaba](https://github.com/smorinlabs/template-press/commit/23baaba406ce88508fec3121fc602d95dcd2a5c4))
* **rules:** parse [[clean]] path declarations ([6cb9e7f](https://github.com/smorinlabs/template-press/commit/6cb9e7f12d034f4c8a0f920995db938171fd8cb1))
* **rules:** parse [[edit]] declarations ([0502dec](https://github.com/smorinlabs/template-press/commit/0502dec8bd91a5f655be7c21a5224680424c1599))
* **verify:** explain dir-only ignore near-misses on untracked findings ([cf3acdd](https://github.com/smorinlabs/template-press/commit/cf3acddfba4750303d0cf667410556b8c150c76d))


### Bug Fixes

* absolute rmdir remedy; skip substring-mode fields in prefix warning; p12 in progress ([eda8b02](https://github.com/smorinlabs/template-press/commit/eda8b02c8b1cd913e18195c9d96e6e8475b4ee9c))
* address bot review on [#109](https://github.com/smorinlabs/template-press/issues/109) — prefix counts, tracked tally, rmdir remedy, scoped restore hint ([6fdcf85](https://github.com/smorinlabs/template-press/commit/6fdcf85bfdda75be90ca6aa27ea333d2a9821bee))
* **ci:** retain pytest output after interrupts ([5cd95f3](https://github.com/smorinlabs/template-press/commit/5cd95f34c78e807f2c735ecd324fa0423ea75c78))
* **clean:** escape command displays without changing arguments ([7893b6a](https://github.com/smorinlabs/template-press/commit/7893b6a28bc67560c9b6866f597b0bdc2547e47b))
* **clean:** handle git metadata encodings without altering paths ([b7ce4af](https://github.com/smorinlabs/template-press/commit/b7ce4aff0c39cea4804cefb5ba7b2c60da918d16))
* **clean:** preserve declared scope with exact file cleanup ([34d9581](https://github.com/smorinlabs/template-press/commit/34d95817e0dd4044c9f1ed9544cb76b5b6beac7e))
* **clean:** verify windows directory entries by identity ([8d6a6a3](https://github.com/smorinlabs/template-press/commit/8d6a6a301c74d75a50de2325aec12674a5b5012d))
* **cli:** keep partial-rewrite guidance on apply-time closure refusals; pin truncation completeness ([2ef456e](https://github.com/smorinlabs/template-press/commit/2ef456e4fa2faa1796b15ba51e4905dc439c1688))
* **cli:** surface closure remedies on apply-time revalidation; scope docs and add coverage ([248a5d4](https://github.com/smorinlabs/template-press/commit/248a5d44dd5f1b08d9fe3be9bf14771a6ae3db81))
* **edit:** make command recovery fail-safe ([47e602c](https://github.com/smorinlabs/template-press/commit/47e602ca8b45162af5c7f1e94681759d04a93f18))
* **edit:** report invalid utf8 without exemption claim ([c937699](https://github.com/smorinlabs/template-press/commit/c93769980cff2fab8498422598358d8aed056617))
* **edit:** restore control files after exceptional command failures ([b786f95](https://github.com/smorinlabs/template-press/commit/b786f95c311f3f987c9c11d06a5737ab2d83a470))
* final-review wave — docs build, posix-only filename tests, wording, rules stub ([81e6b47](https://github.com/smorinlabs/template-press/commit/81e6b478afd366dca5f7c66000f13856f2728b12))
* **guard:** announce origin relaxation only past the plan-time gates ([6418eb8](https://github.com/smorinlabs/template-press/commit/6418eb8721154d107f6f736029adac0a1c587735))
* **guard:** render the discovered origin value with repr; correct absent-key wording and help order ([7cdf09f](https://github.com/smorinlabs/template-press/commit/7cdf09fd65d451493b0fce6abecd6122a248a9d8))
* **p12:** correct recovery guidance and warning coverage ([9b26581](https://github.com/smorinlabs/template-press/commit/9b265813a4ce36da6ae3e170e914949b480a4eab))
* **p12:** correct recovery guidance and warning coverage ([86e0885](https://github.com/smorinlabs/template-press/commit/86e088544cae26b93bff4ff919fbc7d2836a6d6b))
* **plan:** count path-only rewrites, reuse the plan snapshot, key package dir on source identity ([1bd5037](https://github.com/smorinlabs/template-press/commit/1bd50373de9226bd17882ebb48de82c977432048))
* **plan:** prefix warning ignores extension-style continuations; covers display forms ([9a09597](https://github.com/smorinlabs/template-press/commit/9a0959794de4a04e1c9711c8379b034ae2704136))
* **plan:** source-coordinate rename candidacy; discriminating package-dir tests ([7a70512](https://github.com/smorinlabs/template-press/commit/7a705125bf13b3ef7ce18e6b1cc2cc3c25b67c14))
* platform-aware and ancestor-aware rmdir remedy; label common-dir excludes ([bb1f326](https://github.com/smorinlabs/template-press/commit/bb1f326b94a91e51b5e95a806f372a4ed2597344))
* **rebrand:** address ci and review findings ([8f4c739](https://github.com/smorinlabs/template-press/commit/8f4c73956905c110ca936fd9c7798e5a2407e3c1))
* **rebrand:** avoid rollback advice after completion ([a894dc1](https://github.com/smorinlabs/template-press/commit/a894dc17d710a25406bf783fdc30ff6742d2480a))
* **rebrand:** bound interruption recovery guidance ([f8ab220](https://github.com/smorinlabs/template-press/commit/f8ab220419a7347938350d7471111b9ba7def6fe))
* **rebrand:** close declared edit review gaps ([4f641ab](https://github.com/smorinlabs/template-press/commit/4f641ab91167be46dcf8344a9e978e8f4643f43a))
* **rebrand:** guide recovery for all interruptions ([bb5d765](https://github.com/smorinlabs/template-press/commit/bb5d765f2cec28feaa787242ad40a8c909bf3bd4))
* **rebrand:** name the restore path when a receiptless press is retried ([1568dfe](https://github.com/smorinlabs/template-press/commit/1568dfe641f19a601bd81d973e68bee98d91bf67))
* **rebrand:** refuse edits to configured ignore inputs ([ea4b047](https://github.com/smorinlabs/template-press/commit/ea4b0478ca7b246f40f99a1e311f4d0dc6aee49b))
* **rebrand:** refuse unsafe edit declarations before mutation ([7b4731b](https://github.com/smorinlabs/template-press/commit/7b4731b03e536a4a31a9f43290944a2f576623cb))
* **remove:** guard directory history and visibility inputs ([80be8e3](https://github.com/smorinlabs/template-press/commit/80be8e356da235eaa30d4fa4cbf98e8542e7b4c0))
* **remove:** isolate native acceptance identity ([9acedc9](https://github.com/smorinlabs/template-press/commit/9acedc9bb692581a598d07655b954721aa4892ea))
* **remove:** preflight complete directory receipt limits ([e53e533](https://github.com/smorinlabs/template-press/commit/e53e5333cffef7522b885bd559013811cda88a8b))
* **remove:** preserve git inputs and historical safety gates ([b2737a0](https://github.com/smorinlabs/template-press/commit/b2737a0cf77bd300a4a66d7fac7c52b1b837ca9d))
* **rules:** describe component matching precisely ([2eb6631](https://github.com/smorinlabs/template-press/commit/2eb66311220ae06b30ca11172f68bee5986e484f))
* **rules:** keep alias checks fail-closed ([abc3475](https://github.com/smorinlabs/template-press/commit/abc347557483418d8699fc8117631ebcbf0df7a7))
* **rules:** normalize edit target identity ([718e283](https://github.com/smorinlabs/template-press/commit/718e283206f8e5fb9b4e8810649806033bd2cc3d))
* **rules:** normalize unicode edit aliases ([42d7070](https://github.com/smorinlabs/template-press/commit/42d70705a36bd5e5b05f8c3350c53581950f77ef))
* **rules:** preserve edit platform and constructor semantics ([c4462e5](https://github.com/smorinlabs/template-press/commit/c4462e56a259821537d3e9561df15e32378bef22))
* **substitutions:** report every uninventoried path in one closure refusal ([a7ed748](https://github.com/smorinlabs/template-press/commit/a7ed74813c264869c601276cd5c6a5425f3183fc))
* **verify:** bind the receipt by exact identity key set; report binding failures under --json too ([027cd76](https://github.com/smorinlabs/template-press/commit/027cd761ef1416b567448b910a4f409094b1c989))
* **verify:** honor an origin receipt only when it is verified and bound to this target ([d2153f8](https://github.com/smorinlabs/template-press/commit/d2153f82510b71e9c40914ede9e158e984be2dbb))
* **verify:** honor the exact origin values an --accept-origin-mismatch press recorded ([e0772a6](https://github.com/smorinlabs/template-press/commit/e0772a68e9f1d98d703fe90617157115db08749d))
* **verify:** honor the origin values an --accept-origin-mismatch press recorded ([a2418f0](https://github.com/smorinlabs/template-press/commit/a2418f0a3df34082d8a6a4afef2d082b87a7914b))
* **verify:** literal pathspecs, pinned excludes, and note-only-when-present for ignore hints ([2bf9e2d](https://github.com/smorinlabs/template-press/commit/2bf9e2dbf87dd3181e477f0181cbdcc5a956fdf3))


### Performance Improvements

* **ci:** run the test matrix in parallel with pytest-xdist ([e5a2f37](https://github.com/smorinlabs/template-press/commit/e5a2f373c65f7409519fca3ef9f53ec2ed40f207))
* **ci:** run the test matrix in parallel with pytest-xdist ([93674e8](https://github.com/smorinlabs/template-press/commit/93674e8c907b054fc9c121307d8ce750af93e230))
* **rebrand:** batch git rev-parse queries in the config stamp ([bddbae3](https://github.com/smorinlabs/template-press/commit/bddbae3c32a4a8a1c9e6bff62789f7b68156027c))
* **rebrand:** batch git rev-parse queries in the config stamp ([b396c20](https://github.com/smorinlabs/template-press/commit/b396c200f8ab31650fe0d5750208d9c1c4c43cdc))
* **rebrand:** keep newline-bearing git paths intact in the batched stamp ([47a9563](https://github.com/smorinlabs/template-press/commit/47a9563f157fdaa6f34ea11b5ac12056aa85ffc0))

## [4.0.1](https://github.com/smorinlabs/template-press/compare/v4.0.0...v4.0.1) (2026-08-18)


### Bug Fixes

* **engine:** exempt compatible nesting from the rendered-FROM guard ([5d41903](https://github.com/smorinlabs/template-press/commit/5d41903ba26eee23abace09549d23441023553f3)), closes [#44](https://github.com/smorinlabs/template-press/issues/44)
* **engine:** plan-time guard for nested/overlapping rendered rule FROMs ([173c6da](https://github.com/smorinlabs/template-press/commit/173c6dae8e0bb95e3215929580e77ee92c9f64d1))
* **engine:** plan-time guard for nested/overlapping rendered rule FROMs ([00a5c15](https://github.com/smorinlabs/template-press/commit/00a5c15dbee100242ca572e6464ed0373b4c594c)), closes [#44](https://github.com/smorinlabs/template-press/issues/44)
* **rules,receipt:** case-fold control paths, handle non-utf-8 receipts ([ca99778](https://github.com/smorinlabs/template-press/commit/ca99778572ec2fe8c819d6c8ce909e633a6cdc11))
* **rules,receipt:** case-fold control paths, handle non-utf-8 receipts ([4095a08](https://github.com/smorinlabs/template-press/commit/4095a08fbe6c2e681fb6a3634ab506735957def0)), closes [#86](https://github.com/smorinlabs/template-press/issues/86)
* **rules:** reject windows trailing-dot/space control-path aliases ([05ce8b0](https://github.com/smorinlabs/template-press/commit/05ce8b04ea8d17ee71294277ef7bbd3204b6da5d))
* **sandbox:** close 4 more symlink-containment gaps in the pivot walk ([c502cdf](https://github.com/smorinlabs/template-press/commit/c502cdfd20962bce56475356bc0cba5cddbe2b8b))
* **sandbox:** never follow a symlink target outside the target tree ([c093b28](https://github.com/smorinlabs/template-press/commit/c093b2882d4802cb7760029555e5dcdd9caebfe3))
* **sandbox:** never follow a symlink target through an in-tree pivot ([e1ff559](https://github.com/smorinlabs/template-press/commit/e1ff5598eddc8f3480353b39e1c2a8764c789858))
* **sandbox:** recreate directory symlinks with target_is_directory on windows ([90ed9d5](https://github.com/smorinlabs/template-press/commit/90ed9d5a812c42b16602e70a14300d09dcc23244))
* **sandbox:** recreate directory symlinks with target_is_directory on windows ([e733a90](https://github.com/smorinlabs/template-press/commit/e733a9028636fd242c6c9dda8608ed8d28a2125b)), closes [#50](https://github.com/smorinlabs/template-press/issues/50)
* **sandbox:** skip directory-symlink containment probing on POSIX ([00f49d1](https://github.com/smorinlabs/template-press/commit/00f49d1c118a7068fcbc2b74b3c032b056f0bf0b))

## [4.0.0](https://github.com/smorinlabs/template-press/compare/v3.6.0...v4.0.0) (2026-08-18)


### ⚠ BREAKING CHANGES

* minimum supported Python version is now 3.13.

### Bug Fixes

* sync flox/ruff/ADR python floor with the 3.13 bump ([b76baea](https://github.com/smorinlabs/template-press/commit/b76baea1941c31a20b08d23bbb0a4645e094d667))
* **synthesize:** preserve display-form/field equality in synthetic identities ([edf9ce9](https://github.com/smorinlabs/template-press/commit/edf9ce935cf2d5fabb6ac6d972a105e59ab30f1f)), closes [#46](https://github.com/smorinlabs/template-press/issues/46)
* **synthesize:** reserve every display form and cap fallback-seed line length ([a40560a](https://github.com/smorinlabs/template-press/commit/a40560a43bfc6ab17bb9123dac081c44e70ebb86))
* **verify:** honor substring mode in the presence preflight ([01a8db2](https://github.com/smorinlabs/template-press/commit/01a8db285a26f06391e78f55f9902001db221a1b)), closes [#47](https://github.com/smorinlabs/template-press/issues/47)


### Build System

* drop python 3.12 support, require &gt;=3.13 ([cdab101](https://github.com/smorinlabs/template-press/commit/cdab101a2716047092508789d00e288ee8088a40))

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
