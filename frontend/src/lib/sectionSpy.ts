import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Which section of a long page is in view, for "on this page" links (Settings in
 * the sidebar, the Docs / Privacy / Terms table of contents). The current section
 * is the last one whose top has passed a line ~30% down the screen; at the very
 * bottom it's the last one. A section picked from the links stays current until
 * the user scrolls by hand: short sections near the bottom can't scroll up to the line.
 */
export function useSectionSpy(ids: string[]): [string, (id: string) => void] {
  const key = ids.join(',')
  const [current, setCurrent] = useState(ids[0] ?? '')
  const picked = useRef<string | null>(null)

  useEffect(() => {
    const list = key.split(',').filter(Boolean)
    let frame = 0
    const update = () => {
      frame = 0
      if (picked.current || !list.length) return
      const atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4
      if (atBottom) return setCurrent(list[list.length - 1])
      const line = window.innerHeight * 0.3
      let id = list[0]
      for (const candidate of list) {
        const el = document.getElementById(candidate)
        if (el && el.getBoundingClientRect().top <= line) id = candidate
      }
      setCurrent(id)
    }
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(update)
    }
    const release = () => {
      picked.current = null
    }
    update()
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('resize', onScroll)
    for (const ev of ['wheel', 'touchstart', 'keydown'] as const) window.addEventListener(ev, release, { passive: true })
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('resize', onScroll)
      for (const ev of ['wheel', 'touchstart', 'keydown'] as const) window.removeEventListener(ev, release)
    }
  }, [key])

  const pick = useCallback((id: string) => {
    picked.current = id
    setCurrent(id)
  }, [])
  return [current, pick]
}
