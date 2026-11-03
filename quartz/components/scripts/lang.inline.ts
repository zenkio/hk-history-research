// Language switch for pages that carry a Traditional Chinese version next to the English text
// (`.lang-zh` / `.lang-en` spans). Traditional Chinese is the default; text without a Chinese version is
// simply English. The choice is kept in this browser and applies to the whole page, also after navigation.
const KEY = "hk-history-lang"

function stored(): string {
  try {
    return localStorage.getItem(KEY) === "en" ? "en" : "zh"
  } catch {
    return "zh"
  }
}

function apply(lang: string) {
  document.documentElement.setAttribute("data-lang", lang)
  // the page title (heading and browser tab) follows the language when the page carries both titles
  const names = document.querySelector<HTMLElement>(".page-title-i18n")
  const title = names?.dataset[lang === "en" ? "en" : "zh"]
  if (title) {
    const h1 = document.querySelector<HTMLElement>(".article-title, article h1")
    if (h1) h1.textContent = title
    const other = names?.dataset[lang === "en" ? "zh" : "en"]
    document.title = other && document.title.includes(other) ? document.title.replace(other, title) : document.title
  }
  document.querySelectorAll<HTMLElement>(".lang-switch button").forEach((b) => {
    b.setAttribute("aria-pressed", String(b.dataset.lang === lang))
  })
}

document.addEventListener("click", (e) => {
  const button = e.target instanceof Element ? e.target.closest<HTMLElement>(".lang-switch button") : null
  if (!button?.dataset.lang) return
  try {
    localStorage.setItem(KEY, button.dataset.lang)
  } catch {
    /* the choice just is not kept */
  }
  apply(button.dataset.lang)
})

apply(stored())
document.addEventListener("nav", () => apply(stored()))
