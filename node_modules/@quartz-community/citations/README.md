# @quartz-community/citations

Adds academic citation support using a BibTeX bibliography file and configurable citation styles.

## Installation

```bash
npx quartz plugin add github:quartz-community/citations
```

## Usage

```yaml title="quartz.config.yaml"
plugins:
  - source: github:quartz-community/citations
    enabled: true
    options:
      bibliographyFile: "./bibliography.bib"
      csl: apa
```

For advanced use cases, you can override in TypeScript:

```ts title="quartz.ts (override)"
import * as ExternalPlugin from "./.quartz/plugins";

ExternalPlugin.Citations({
  bibliographyFile: "./bibliography.bib",
  csl: "apa",
});
```

## Configuration

| Option                 | Type      | Default                | Description                                                  |
| ---------------------- | --------- | ---------------------- | ------------------------------------------------------------ |
| `bibliographyFile`     | `string`  | `"./bibliography.bib"` | The path to the BibTeX bibliography file.                    |
| `suppressBibliography` | `boolean` | `false`                | Whether to suppress the bibliography at the end of the page. |
| `linkCitations`        | `boolean` | `false`                | Whether to link citations to the bibliography.               |
| `csl`                  | `string`  | `"apa"`                | The CSL style to use for citations.                          |

## Documentation

See the [Quartz documentation](https://quartz.jzhao.xyz/plugins/Citations) for more information.

## License

MIT
