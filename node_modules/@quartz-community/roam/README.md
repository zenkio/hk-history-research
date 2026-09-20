# @quartz-community/roam

Transforms Roam Research markdown syntax including {{or:}} selectors, TODO/DONE checkboxes, media embeds, and Roam-style highlights.

## Installation

```bash
npx quartz plugin add github:quartz-community/roam
```

## Usage

```yaml title="quartz.config.yaml"
plugins:
  - source: github:quartz-community/roam
    enabled: true
```

For advanced use cases, you can override in TypeScript:

```ts title="quartz.ts (override)"
import * as ExternalPlugin from "./.quartz/plugins";

ExternalPlugin.RoamFlavoredMarkdown({
  orComponent: true,
  TODOComponent: true,
});
```

## Configuration

| Option                | Type      | Default | Description                                 |
| --------------------- | --------- | ------- | ------------------------------------------- |
| `orComponent`         | `boolean` | `true`  | Whether to enable the {{or:}} component.    |
| `TODOComponent`       | `boolean` | `true`  | Whether to enable the TODO component.       |
| `DONEComponent`       | `boolean` | `true`  | Whether to enable the DONE component.       |
| `videoComponent`      | `boolean` | `true`  | Whether to enable the video component.      |
| `audioComponent`      | `boolean` | `true`  | Whether to enable the audio component.      |
| `pdfComponent`        | `boolean` | `true`  | Whether to enable the PDF component.        |
| `blockquoteComponent` | `boolean` | `true`  | Whether to enable the blockquote component. |
| `tableComponent`      | `boolean` | `true`  | Whether to enable the table component.      |
| `attributeComponent`  | `boolean` | `true`  | Whether to enable the attribute component.  |

## Documentation

See the [Quartz documentation](https://quartz.jzhao.xyz/plugins/RoamFlavoredMarkdown) for more information.

## License

MIT
