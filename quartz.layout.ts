import { PageLayout, SharedLayout } from "./quartz/cfg"
import * as Component from "./quartz/components"

export const defaultPageLayout: PageLayout = {
  beforeBody: [
    Component.Breadcrumbs(),
    Component.ArticleTitle(),
    Component.ContentMeta(),
    Component.TagList(),
  ],
  left: [
    Component.PageTitle(),
    Component.MobileOnly(Component.Spacer()),
    Component.Search(),
    Component.Darkmode(),
    Component.DesktopOnly(Component.Explorer()),
  ],
  right: [
    Component.Graph({
      localGraph: { drag: true, zoom: true, depth: 2, scale: 1.1, repelForce: 0.5, centerForce: 0.3, linkDistance: 30, fontSize: 0.6, opacityScale: 1 },
      globalGraph: { drag: true, zoom: true, depth: -1, scale: 0.9, repelForce: 0.5, centerForce: 0.3, linkDistance: 30, fontSize: 0.6, opacityScale: 1 },
    }),
    Component.DesktopOnly(Component.TableOfContents()),
    Component.Backlinks(),
  ],
}
