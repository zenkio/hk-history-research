import { QuartzComponent } from '@quartz-community/types';

interface ExampleComponentOptions {
    prefix?: string;
    suffix?: string;
    className?: string;
}
declare const _default$1: (opts?: ExampleComponentOptions) => QuartzComponent;

interface StackedPagesComponentOptions {
    maxTabs?: number;
    mobileBreakpoint?: number;
    showSpines?: boolean;
    animateTransitions?: boolean;
}
declare const _default: (opts?: StackedPagesComponentOptions) => QuartzComponent;

export { _default$1 as ExampleComponent, type ExampleComponentOptions, _default as StackedPages, type StackedPagesComponentOptions };
