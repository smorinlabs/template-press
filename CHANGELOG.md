# Changelog

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
