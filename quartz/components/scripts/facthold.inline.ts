// Consolidated multi-AI pages on touch screens: hold a sentence for a moment to see which AIs back it
// (the hover tip does not exist there). A tap elsewhere closes it. Listeners sit on the document, so they
// work on every page and survive SPA navigation.
const HOLD_MS = 1300
const SLACK_PX = 12 // a real finger always jitters a little; only a real drag (scrolling) cancels the hold
let startX = 0
let startY = 0
let timer: number | undefined
let open: Element | null = null

function cancel() {
  if (timer !== undefined) window.clearTimeout(timer)
  timer = undefined
}

function close() {
  open?.classList.remove("hold-open")
  open = null
}

function sentenceAt(target: EventTarget | null): Element | null {
  return target instanceof Element ? target.closest(".consolidated .sent") : null
}

document.addEventListener(
  "touchstart",
  (e) => {
    cancel()
    startX = e.touches[0]?.clientX ?? 0
    startY = e.touches[0]?.clientY ?? 0
    const sentence = sentenceAt(e.target)
    if (!sentence) {
      close()
      return
    }
    timer = window.setTimeout(() => {
      close()
      sentence.classList.add("hold-open")
      open = sentence
    }, HOLD_MS)
  },
  { passive: true },
)

for (const name of ["touchend", "touchcancel"]) {
  document.addEventListener(name, cancel, { passive: true })
}

document.addEventListener(
  "touchmove",
  (e) => {
    const t = e.touches[0]
    if (t && Math.hypot(t.clientX - startX, t.clientY - startY) > SLACK_PX) cancel()
  },
  { passive: true },
)

// The browser's own long-press menu / text selection must not fire on a held sentence.
document.addEventListener("contextmenu", (e) => {
  if (sentenceAt(e.target)) e.preventDefault()
})
