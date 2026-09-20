export { BuildCtx, CSSResource, ChangeEvent, JSResource, PageGenerator, PageMatcher, ProcessedContent, QuartzEmitterPlugin, QuartzEmitterPluginInstance, QuartzFilterPlugin, QuartzFilterPluginInstance, QuartzPageTypePlugin, QuartzPageTypePluginInstance, QuartzPluginData, QuartzTransformerPlugin, QuartzTransformerPluginInstance, StaticResources, VirtualPage } from '@quartz-community/types';

interface StackedPagesOptions {
    /** Maximum number of tabs in the binder (including the active page). Oldest tabs are evicted. Default: 8 */
    maxTabs: number;
    /** Hide the binder UI on viewports narrower than this (px). Default: 800 */
    mobileBreakpoint: number;
    /** Show the accent-colored spine on each tab. Default: true */
    showSpines: boolean;
    /** Enable slide animations when switching tabs. Default: true */
    animateTransitions: boolean;
}
interface ExampleTransformerOptions {
    highlightToken: string;
    headingClass: string;
    enableGfm: boolean;
    addHeadingSlugs: boolean;
}
interface ExampleFilterOptions {
    allowDrafts: boolean;
    excludeTags: string[];
    excludePathPrefixes: string[];
}
interface ExampleEmitterOptions {
    manifestSlug: string;
    includeFrontmatter: boolean;
    metadata: Record<string, unknown>;
    transformManifest?: (json: string) => string;
    manifestScriptClass?: string;
}
interface ExampleComponentOptions {
    prefix?: string;
    suffix?: string;
    className?: string;
}

export type { ExampleComponentOptions, ExampleEmitterOptions, ExampleFilterOptions, ExampleTransformerOptions, StackedPagesOptions };
