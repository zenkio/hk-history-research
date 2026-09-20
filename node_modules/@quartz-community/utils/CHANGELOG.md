## 1.0.1

### Patch Changes

- Add `preact` to devDependencies so the package can be built from source.

  `src/jsx.tsx` imports `preact` and `preact/jsx-runtime`, and the build emits declarations
  (`dts: true`), so TypeScript needs preact types at build time. It was declared only as a
  required peer dependency, and Quartz sets `legacy-peer-deps=true`, so npm did not install
  it when building from a `github:` source. Builds failed with TS2307 and TS2875.

# Changelog

## 1.0.0

### Major Changes

- Stable 1.0 release. All `@quartz-community/*` dependencies now use `^1.0.0` ranges.

  Pre-1.0 caret ranges pinned the minor version (`^0.2.1` means `>=0.2.1 <0.3.0`), so
  published fixes to shared packages could never be resolved by dependents. Moving the
  ecosystem to 1.0 makes caret ranges behave conventionally.

## 0.1.1

### Patch Changes

- 1eb2dd8: Fix `getFullSlugFromUrl()` to decode URI-encoded pathnames. Non-ASCII characters (Cyrillic, Chinese, etc.) in page titles were URL-encoded in the browser pathname but not decoded before slug comparison, causing mismatches in graph, search, and other client-side features.

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial Quartz community plugin template.

### Changed

- **BREAKING**: `slugifyPath`, `slugifyFilePath`, and `slugTag` now lowercase their output to match Obsidian's case-insensitive link- and tag-matching semantics. Previously all three preserved case. This means `[[My Note]]` and `[[my note]]` both resolve to the slug `my-note`, and the tags `#MyTag` and `#mytag` collapse into a single tag page. Downstream effects: all generated URLs are now lowercase; users upgrading from earlier Quartz v5 betas with mixed-case source filenames will see their URLs change (e.g. `/MyNote` → `/my-note`). Also eliminates silent data loss on case-insensitive filesystems (macOS APFS, Windows NTFS), where `Apple.md` and `apple.md` previously produced conflicting HTML outputs that overwrote each other without warning.
