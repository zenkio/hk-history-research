import { QuartzTransformerPlugin } from '@quartz-community/types';
export { QuartzTransformerPlugin } from '@quartz-community/types';

interface CitationsOptions {
    bibliographyFile: string;
    suppressBibliography: boolean;
    linkCitations: boolean;
    csl: string;
}
declare const Citations: QuartzTransformerPlugin<Partial<CitationsOptions>>;

export { Citations, type CitationsOptions };
