import { QuartzPluginData, SortFn, QuartzComponent, GlobalConfiguration, ValidDateType } from '@quartz-community/types';

type RecentNotesPluginData = QuartzPluginData & Record<string, unknown>;
interface RecentNotesOptions {
    title?: string;
    limit: number;
    linkToMore: string | false;
    showTags: boolean;
    hideTagPages: boolean;
    hideFolderPages: boolean;
    filter: (f: RecentNotesPluginData) => boolean;
    sort: SortFn;
}
/**
 * Resolve the defaultDateType for a given page, preferring the per-file value
 * set by the CreatedModifiedDate transformer, falling back to the global config.
 */
declare function resolveDefaultDateType(data: RecentNotesPluginData, cfg: GlobalConfiguration): ValidDateType | undefined;
/**
 * Return a copy of the page data with the resolved defaultDateType applied,
 * so that getDate() from @quartz-community/utils/sort can read it.
 */
declare const withResolvedDateType: (data: RecentNotesPluginData, cfg: GlobalConfiguration) => QuartzPluginData;
declare function filterListedPages<T>(pages: T[]): T[];
/** True for Quartz tag-index slugs: `tags`, `tags/index`, or `tags/<anything>`. */
declare function isTagPageSlug(slug: string | undefined): boolean;
/** True for Quartz folder-index slugs; delegates to `isFolderPath` from `@quartz-community/utils`. */
declare function isFolderPageSlug(slug: string | undefined): boolean;
declare const _default: (userOpts?: Partial<RecentNotesOptions>) => QuartzComponent;

export { _default as RecentNotes, type RecentNotesOptions, isTagPageSlug as a, filterListedPages as f, isFolderPageSlug as i, resolveDefaultDateType as r, withResolvedDateType as w };
