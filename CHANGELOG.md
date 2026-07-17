# Changelog

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
