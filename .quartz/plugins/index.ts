import { componentRegistry } from "../../quartz/components/registry"

export type { CreatedModifiedDateOptions } from "@quartz-community/created-modified-date"
export type { SyntaxHighlightingOptions } from "@quartz-community/syntax-highlighting"
export type { ObsidianFlavoredMarkdownOptions } from "@quartz-community/obsidian-flavored-markdown"
export type { GfmOptions } from "@quartz-community/github-flavored-markdown"
export type { TableOfContentsTransformerOptions, TocEntry } from "@quartz-community/table-of-contents"
export type { CrawlLinksOptions } from "@quartz-community/crawl-links"
export type { DescriptionOptions } from "@quartz-community/description"
export type { Args, LatexOptions } from "@quartz-community/latex"
export type { FontFileEntry, FontSpecification, GoogleFontFile, ProcessedFontResult, QuartzFontRegistry, FontsOptions } from "@quartz-community/quartz-fonts"
export type { ContentDetails, ContentIndexMap } from "@quartz-community/content-index"
export type { ImageOptions, SocialImageFileData, SocialImageOptions, UserOpts } from "@quartz-community/og-image"
export type { CanvasBackgroundStyle, CanvasColor, CanvasData, CanvasEdge, CanvasEnd, CanvasFileNode, CanvasGroupNode, CanvasLinkNode, CanvasNode, CanvasSide, CanvasTextNode, CanvasPageOptions } from "@quartz-community/canvas-page"
export type { ContentPageOptions, ContentBodyOptions } from "@quartz-community/content-page"
export type { FolderPageOptions } from "@quartz-community/folder-page"
export type { TagPageOptions } from "@quartz-community/tag-page"
export type { ExplorerOptions } from "@quartz-community/explorer"
export type { D3Config, GraphOptions } from "@quartz-community/graph"
export type { SearchField, SearchOptions } from "@quartz-community/search"
export type { BacklinksOptions } from "@quartz-community/backlinks"
export type { ContentMetaOptions } from "@quartz-community/content-meta"
export type { BreadcrumbOptions } from "@quartz-community/breadcrumbs"
export type { FooterOptions } from "@quartz-community/footer"
export type { RecentNotesOptions } from "@quartz-community/recent-notes"
export type { BasesEntry, BasesView, FilterNode, GroupBy, PropertyConfig, SortDirection, SummaryType, ViewRenderer, ViewRendererProps, ViewTypeRegistration, BasesData, BasesPageOptions } from "@quartz-community/bases-page"
export type { NotePropertiesComponentOptions, NotePropertiesOptions } from "@quartz-community/note-properties"
export type { ShadowContentIndexEntry, ShadowIndexBlob, ShadowIndexFile, EncryptedPageComponentOptions, EncryptedContentIndexOptions, EncryptedPagesOptions } from "@quartz-community/encrypted-pages"
export { tokenClassifierTransformer } from "@quartz-community/syntax-highlighting"
export { TableOfContents } from "@quartz-community/table-of-contents"
export { FontsEmitter } from "@quartz-community/quartz-fonts"
export { CustomOgImagesEmitterName } from "@quartz-community/og-image"
export { CanvasBody, CanvasFrame } from "@quartz-community/canvas-page"
export { ContentBody } from "@quartz-community/content-page"
export { FolderPage, FolderContent } from "@quartz-community/folder-page"
export { TagPage, TagContent } from "@quartz-community/tag-page"
export { Explorer } from "@quartz-community/explorer"
export { Graph } from "@quartz-community/graph"
export { Search } from "@quartz-community/search"
export { Backlinks } from "@quartz-community/backlinks"
export { ArticleTitle } from "@quartz-community/article-title"
export { ContentMeta } from "@quartz-community/content-meta"
export { TagList } from "@quartz-community/tag-list"
export { PageTitle } from "@quartz-community/page-title"
export { Darkmode } from "@quartz-community/darkmode"
export { ReaderMode } from "@quartz-community/reader-mode"
export { Breadcrumbs } from "@quartz-community/breadcrumbs"
export { Footer } from "@quartz-community/footer"
export { RecentNotes, filterListedPages, isFolderPageSlug, isTagPageSlug, resolveDefaultDateType, withResolvedDateType } from "@quartz-community/recent-notes"
export { Spacer } from "@quartz-community/spacer"
export { BasesBody, registerCustomViews, viewRegistry, compile, evaluate, evaluateFilter, resolvePropertyValue } from "@quartz-community/bases-page"
export { NotePropertiesComponent } from "@quartz-community/note-properties"
export { EncryptedPage, SHADOW_INDEX_VERSION, decrypt, encryptAesGcm } from "@quartz-community/encrypted-pages"

export const plugins: Record<string, Record<string, (...args: unknown[]) => void>> = {
  "quartz-community__created-modified-date": {
    CreatedModifiedDate: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__created-modified-date", args[0] as Record<string, unknown>); },
  },
  "quartz-community__syntax-highlighting": {
    SyntaxHighlighting: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__syntax-highlighting", args[0] as Record<string, unknown>); },
  },
  "quartz-community__obsidian-flavored-markdown": {
    ObsidianFlavoredMarkdown: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__obsidian-flavored-markdown", args[0] as Record<string, unknown>); },
  },
  "quartz-community__github-flavored-markdown": {
    GitHubFlavoredMarkdown: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__github-flavored-markdown", args[0] as Record<string, unknown>); },
  },
  "quartz-community__table-of-contents": {
    TableOfContentsTransformer: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__table-of-contents", args[0] as Record<string, unknown>); },
  },
  "quartz-community__crawl-links": {
    CrawlLinks: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__crawl-links", args[0] as Record<string, unknown>); },
  },
  "quartz-community__description": {
    Description: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__description", args[0] as Record<string, unknown>); },
  },
  "quartz-community__latex": {
    Latex: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__latex", args[0] as Record<string, unknown>); },
  },
  "quartz-community__quartz-fonts": {
    Fonts: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__quartz-fonts", args[0] as Record<string, unknown>); },
  },
  "quartz-community__remove-draft": {
    RemoveDrafts: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__remove-draft", args[0] as Record<string, unknown>); },
  },
  "quartz-community__alias-redirects": {
    AliasRedirects: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__alias-redirects", args[0] as Record<string, unknown>); },
  },
  "quartz-community__content-index": {
    ContentIndex: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__content-index", args[0] as Record<string, unknown>); },
  },
  "quartz-community__favicon": {
    Favicon: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__favicon", args[0] as Record<string, unknown>); },
  },
  "quartz-community__og-image": {
    CustomOgImages: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__og-image", args[0] as Record<string, unknown>); },
  },
  "quartz-community__cname": {
    CNAME: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__cname", args[0] as Record<string, unknown>); },
  },
  "quartz-community__canvas-page": {
    CanvasPage: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__canvas-page", args[0] as Record<string, unknown>); },
  },
  "quartz-community__content-page": {
    ContentPage: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__content-page", args[0] as Record<string, unknown>); },
  },
  "quartz-community__bases-page": {
    BasesPage: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__bases-page", args[0] as Record<string, unknown>); },
    BasesTransformer: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__bases-page", args[0] as Record<string, unknown>); },
  },
  "quartz-community__note-properties": {
    NoteProperties: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__note-properties", args[0] as Record<string, unknown>); },
  },
  "quartz-community__unlisted-pages": {
    UnlistedPages: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__unlisted-pages", args[0] as Record<string, unknown>); },
  },
  "quartz-community__encrypted-pages": {
    EncryptedContentIndex: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__encrypted-pages", args[0] as Record<string, unknown>); },
    EncryptedPages: (...args: unknown[]) => { componentRegistry.setOptionOverrides("quartz-community__encrypted-pages", args[0] as Record<string, unknown>); },
  },
}

export const CreatedModifiedDate = plugins["quartz-community__created-modified-date"].CreatedModifiedDate
export const SyntaxHighlighting = plugins["quartz-community__syntax-highlighting"].SyntaxHighlighting
export const ObsidianFlavoredMarkdown = plugins["quartz-community__obsidian-flavored-markdown"].ObsidianFlavoredMarkdown
export const GitHubFlavoredMarkdown = plugins["quartz-community__github-flavored-markdown"].GitHubFlavoredMarkdown
export const TableOfContentsTransformer = plugins["quartz-community__table-of-contents"].TableOfContentsTransformer
export const CrawlLinks = plugins["quartz-community__crawl-links"].CrawlLinks
export const Description = plugins["quartz-community__description"].Description
export const Latex = plugins["quartz-community__latex"].Latex
export const Fonts = plugins["quartz-community__quartz-fonts"].Fonts
export const RemoveDrafts = plugins["quartz-community__remove-draft"].RemoveDrafts
export const AliasRedirects = plugins["quartz-community__alias-redirects"].AliasRedirects
export const ContentIndex = plugins["quartz-community__content-index"].ContentIndex
export const Favicon = plugins["quartz-community__favicon"].Favicon
export const CustomOgImages = plugins["quartz-community__og-image"].CustomOgImages
export const CNAME = plugins["quartz-community__cname"].CNAME
export const CanvasPage = plugins["quartz-community__canvas-page"].CanvasPage
export const ContentPage = plugins["quartz-community__content-page"].ContentPage
export const BasesPage = plugins["quartz-community__bases-page"].BasesPage
export const BasesTransformer = plugins["quartz-community__bases-page"].BasesTransformer
export const NoteProperties = plugins["quartz-community__note-properties"].NoteProperties
export const UnlistedPages = plugins["quartz-community__unlisted-pages"].UnlistedPages
export const EncryptedContentIndex = plugins["quartz-community__encrypted-pages"].EncryptedContentIndex
export const EncryptedPages = plugins["quartz-community__encrypted-pages"].EncryptedPages
