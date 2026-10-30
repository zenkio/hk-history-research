// Consolidated multi-AI pages on touch screens: hold a sentence for 2 seconds to see which AIs back it
// (the hover tip does not exist there). A tap elsewhere closes it. Listeners sit on the document, so they
// work on every page and survive SPA navigation.
const HOLD_MS = 2000
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

for (const name of ["touchend", "touchmove", "touchcancel"]) {
  document.addEventListener(name, cancel, { passive: true })
}

// The browser's own long-press menu / text selection must not fire on a held sentence.
document.addEventListener("contextmenu", (e) => {
  if (sentenceAt(e.target)) e.preventDefault()
})
