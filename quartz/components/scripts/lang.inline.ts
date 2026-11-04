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
    const plain = (t: string) => t.replace(/[⟦⟧]/g, "")
    if (h1) {
      // Chinese proper-name mark (專名號): names between ⟦ ⟧ are underlined in the heading; the tab cannot hold markup
      h1.textContent = ""
      title.split(/(⟦[^⟦⟧]+⟧)/).forEach((part) => {
        if (/^⟦.*⟧$/.test(part)) {
          const span = document.createElement("span")
          span.className = "pn"
          span.textContent = plain(part)
          h1.appendChild(span)
        } else if (part) h1.appendChild(document.createTextNode(part))
      })
    }
    const other = names?.dataset[lang === "en" ? "zh" : "en"]
    document.title =
      other && document.title.includes(plain(other))
        ? document.title.replace(plain(other), plain(title))
        : document.title
  }
  document.querySelectorAll<HTMLElement>(".lang-switch button").forEach((b) => {
    b.setAttribute("aria-pressed", String(b.dataset.lang === lang))
  })
  applyMenu(lang)
}

// ---- global language switch (left sidebar) and Chinese names in the left menu ----
let titlesZh: Record<string, string> | null = null
let titlesLoading = false

async function loadTitles() {
  if (titlesZh || titlesLoading) return
  titlesLoading = true
  try {
    const res = await fetch("/static/titles-zh.json")
    titlesZh = res.ok ? await res.json() : {}
  } catch {
    titlesZh = {}
  }
  applyMenu(stored())
}

function slugOf(el: Element): string {
  const folder = (el as HTMLElement).dataset?.folderpath
  if (folder) return folder.replace(/\/$/, "")
  const href = el.getAttribute("href")
  if (!href) return ""
  const path = new URL(href, location.href).pathname
  return decodeURIComponent(path).replace(/^\//, "").replace(/\.html$/, "").replace(/\/(index)?$/, "")
}

function applyMenu(lang: string) {
  if (!titlesZh) return void loadTitles()
  document.querySelectorAll<HTMLElement>(".explorer a[href], .explorer [data-folderpath]").forEach((el) => {
    const target = el.querySelector<HTMLElement>(".folder-title") ?? (el.children.length === 0 ? el : null)
    if (!target) return
    if (target.dataset.en === undefined) target.dataset.en = target.textContent ?? ""
    const zh = lang === "zh" ? titlesZh![slugOf(el)] : undefined
    const wanted = zh ?? target.dataset.en
    if (target.textContent !== wanted) target.textContent = wanted
  })
}

function ensureGlobalSwitch(lang: string) {
  const side = document.querySelector<HTMLElement>(".sidebar.left")
  if (!side || side.querySelector(".lang-switch.global")) return
  const box = document.createElement("span")
  box.className = "lang-switch global"
  box.setAttribute("role", "group")
  box.setAttribute("aria-label", "Language")
  box.innerHTML = '<button type="button" data-lang="zh">中文</button><button type="button" data-lang="en">English</button>'
  const explorer = side.querySelector(".explorer")
  if (explorer) explorer.before(box)
  else side.appendChild(box)
  document.body.classList.add("has-global-lang")
  apply(lang)
}

// ---- the graph: collapsible (closed by default, the choice is kept) with a short how-to ----
const GRAPH_KEY = "hk-history-graph-open"

function setupGraph() {
  const graph = document.querySelector<HTMLElement>(".graph")
  const title = graph?.querySelector("h3")
  if (!graph || !title || graph.querySelector(".graph-help")) return
  let open = false
  try {
    open = localStorage.getItem(GRAPH_KEY) === "1"
  } catch {
    /* closed */
  }
  graph.classList.toggle("collapsed", !open)
  title.setAttribute("role", "button")
  title.setAttribute("tabindex", "0")
  title.setAttribute("aria-expanded", String(open))
  title.classList.add("graph-toggle")
  const help = document.createElement("p")
  help.className = "graph-help"
  help.innerHTML =
    '<span class="lang-zh">每個點是一頁，連線表示兩頁互相連結；較亮較大的點是你現在讀的這一頁。點一個點就會打開那一頁，滾輪可放大縮小。右下角的按鈕會打開全站地圖。</span>' +
    '<span class="lang-en" lang="en">Each dot is a page and a line means the two pages link to each other. The larger, brighter dot is the page you are reading. Click a dot to open that page; scroll to zoom. The button in the corner opens the map of the whole site.</span>'
  title.after(help)
  const toggle = () => {
    const nowOpen = graph.classList.toggle("collapsed") === false
    title.setAttribute("aria-expanded", String(nowOpen))
    try {
      localStorage.setItem(GRAPH_KEY, nowOpen ? "1" : "0")
    } catch {
      /* not kept */
    }
  }
  title.addEventListener("click", toggle)
  title.addEventListener("keydown", (e) => {
    if ((e as KeyboardEvent).key === "Enter" || (e as KeyboardEvent).key === " ") {
      e.preventDefault()
      toggle()
    }
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

function setup() {
  ensureGlobalSwitch(stored())
  setupGraph()
  apply(stored())
  const explorer = document.querySelector(".explorer")
  if (explorer instanceof HTMLElement && !explorer.dataset.langObserved) {
    explorer.dataset.langObserved = "1"
    new MutationObserver(() => applyMenu(stored())).observe(explorer, { childList: true, subtree: true })
  }
}

setup()
document.addEventListener("nav", setup)
