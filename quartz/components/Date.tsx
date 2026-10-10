import { ValidLocale } from "../i18n"
import { QuartzPluginData } from "../plugins/vfile"

interface Props {
  date: Date
  locale?: ValidLocale
}

export type ValidDateType = keyof Required<QuartzPluginData>["dates"]

export function getDate(data: QuartzPluginData): Date | undefined {
  if (!data.defaultDateType) {
    throw new Error(
      `Field 'defaultDateType' was not set. Ensure the CreatedModifiedDate plugin is configured with a 'defaultDateType' option. See https://quartz.jzhao.xyz/plugins/CreatedModifiedDate for more details.`,
    )
  }
  return data.dates?.[data.defaultDateType]
}

export function formatDate(d: Date, locale: ValidLocale = "en-US"): string {
  // Year-only frontmatter dates are parsed as 1 January by JavaScript.
  // Render that sentinel as a year rather than inventing day/month precision.
  if (d.getMonth() === 0 && d.getDate() === 1) {
    return d.toLocaleDateString(locale, { year: "numeric", timeZone: "UTC" })
  }

  return d.toLocaleDateString(locale, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    timeZone: "UTC",
  })
}

export function Date({ date, locale }: Props) {
  return <time datetime={date.toISOString()}>{formatDate(date, locale)}</time>
}
