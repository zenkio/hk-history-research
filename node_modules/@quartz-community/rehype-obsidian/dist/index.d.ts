import { Root } from 'hast';

type VFileLike = {
    data?: Record<string, unknown>;
};
declare const blockReferences: (tree: Root, file: VFileLike) => void;

declare const checkbox: (tree: Root) => void;

declare const mermaidExpand: (tree: Root) => void;

declare const obsidianUri: (tree: Root) => void;

declare const tweetEmbed: (tree: Root) => Promise<void>;

declare const youTubeEmbed: (tree: Root) => void;

interface RehypeObsidianOptions {
    blockReferences?: boolean;
    youTubeEmbed?: boolean;
    tweetEmbed?: boolean;
    checkbox?: boolean;
    mermaid?: boolean;
    obsidianUri?: boolean;
}
declare function rehypeObsidian(userOpts?: RehypeObsidianOptions): (tree: Root, file: {
    data?: Record<string, unknown>;
}) => Promise<void>;

export { type RehypeObsidianOptions, blockReferences, checkbox, rehypeObsidian as default, mermaidExpand, obsidianUri, tweetEmbed, youTubeEmbed };
