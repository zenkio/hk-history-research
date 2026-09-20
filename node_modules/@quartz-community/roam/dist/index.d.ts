import { QuartzTransformerPlugin } from '@quartz-community/types';
export { QuartzTransformerPlugin } from '@quartz-community/types';

interface RoamOptions {
    orComponent: boolean;
    TODOComponent: boolean;
    DONEComponent: boolean;
    videoComponent: boolean;
    audioComponent: boolean;
    pdfComponent: boolean;
    blockquoteComponent: boolean;
    tableComponent: boolean;
    attributeComponent: boolean;
}
declare const RoamFlavoredMarkdown: QuartzTransformerPlugin<Partial<RoamOptions> | undefined>;

export { RoamFlavoredMarkdown, type RoamOptions };
