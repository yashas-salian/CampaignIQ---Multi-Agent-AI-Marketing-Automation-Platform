import { useEffect, useId, useLayoutEffect, useRef, useState, type CSSProperties, type KeyboardEvent, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

import css from './Select.module.css'

export interface SelectOption<V extends string | number = string> {
  value: V
  label: ReactNode
  /** Plain text for type-to-jump when `label` isn't a string. */
  text?: string
  disabled?: boolean
}

interface SelectProps<V extends string | number> {
  value: V
  options: SelectOption<V>[]
  onChange: (value: V) => void
  'aria-label'?: string
  id?: string
  disabled?: boolean
  /** Extra class for the closed button (e.g. the dark top-bar variant). */
  className?: string
  /** "tile" matches the black nav tiles in the top bar. */
  variant?: 'field' | 'tile'
}

/**
 * Themed replacement for <select>: the open list of a native select is drawn
 * by the operating system and ignores the site's theme. Keyboard and screen
 * reader behaviour follows the WAI-ARIA "select-only combobox" pattern.
 */
export default function Select<V extends string | number>({
  value,
  options,
  onChange,
  id,
  disabled,
  className,
  variant = 'field',
  'aria-label': ariaLabel,
}: SelectProps<V>) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [place, setPlace] = useState<CSSProperties>({})
  const rootRef = useRef<HTMLDivElement>(null)
  const listRef = useRef<HTMLUListElement>(null)
  const typed = useRef({ text: '', at: 0 })
  const listId = useId()
  const selectedIndex = Math.max(0, options.findIndex((o) => o.value === value))
  const selected = options[selectedIndex]

  useEffect(() => {
    if (!open) return
    const onDown = (e: PointerEvent) => {
      const target = e.target as Node
      if (!rootRef.current?.contains(target) && !listRef.current?.contains(target)) setOpen(false)
    }
    document.addEventListener('pointerdown', onDown)
    return () => document.removeEventListener('pointerdown', onDown)
  }, [open])

  // The list is portalled to <body> with fixed positioning, so no parent's
  // overflow can clip it. It opens upwards when there isn't room below, and
  // follows the button on scroll and resize.
  useLayoutEffect(() => {
    if (!open) return
    const place = () => {
      const box = rootRef.current?.getBoundingClientRect()
      const list = listRef.current
      if (!box || !list) return
      const height = Math.min(list.scrollHeight, 280)
      const up = box.bottom + height + 12 > window.innerHeight && box.top > height + 12
      const width = Math.max(box.width, variant === 'tile' ? 160 : 0)
      const left = Math.min(variant === 'tile' ? box.right - width : box.left, window.innerWidth - width - 8)
      setPlace({
        left: Math.max(8, left),
        minWidth: width,
        ...(up ? { bottom: window.innerHeight - box.top + 6 } : { top: box.bottom + 6 }),
        transformOrigin: up ? 'bottom' : 'top',
      })
    }
    place()
    window.addEventListener('scroll', place, true)
    window.addEventListener('resize', place)
    return () => {
      window.removeEventListener('scroll', place, true)
      window.removeEventListener('resize', place)
    }
  }, [open, variant])
  useEffect(() => {
    if (open) listRef.current?.children[active]?.scrollIntoView({ block: 'nearest' })
  }, [open, active])

  const enabled = (i: number) => options[i] && !options[i].disabled
  const step = (from: number, dir: 1 | -1) => {
    for (let i = from + dir; i >= 0 && i < options.length; i += dir) if (enabled(i)) return i
    return from
  }

  function openAt(index: number) {
    setActive(index)
    setOpen(true)
  }

  function choose(index: number) {
    if (!enabled(index)) return
    setOpen(false)
    if (options[index].value !== value) onChange(options[index].value)
  }

  function typeAhead(key: string) {
    const now = Date.now()
    typed.current = { text: (now - typed.current.at < 700 ? typed.current.text : '') + key.toLowerCase(), at: now }
    const label = (o: SelectOption<V>) => (o.text ?? (typeof o.label === 'string' ? o.label : String(o.value))).toLowerCase()
    const start = open ? active : selectedIndex
    const order = [...options.keys()].slice(start + 1).concat([...options.keys()].slice(0, start + 1))
    const hit = order.find((i) => enabled(i) && label(options[i]).startsWith(typed.current.text))
    if (hit === undefined) return
    if (open) setActive(hit)
    else choose(hit)
  }

  function onKeyDown(e: KeyboardEvent) {
    if (disabled) return
    if (!open) {
      if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(e.key)) {
        e.preventDefault()
        openAt(selectedIndex)
      } else if (e.key.length === 1 && /\S/.test(e.key)) {
        typeAhead(e.key)
      }
      return
    }
    switch (e.key) {
      case 'ArrowDown':
        e.preventDefault()
        setActive((i) => step(i, 1))
        break
      case 'ArrowUp':
        e.preventDefault()
        setActive((i) => step(i, -1))
        break
      case 'Home':
        e.preventDefault()
        setActive(step(-1, 1))
        break
      case 'End':
        e.preventDefault()
        setActive(step(options.length, -1))
        break
      case 'Enter':
      case ' ':
        e.preventDefault()
        choose(active)
        break
      case 'Escape':
        e.preventDefault()
        setOpen(false)
        break
      case 'Tab':
        setOpen(false)
        break
      default:
        if (e.key.length === 1 && /\S/.test(e.key)) typeAhead(e.key)
    }
  }

  return (
    <div ref={rootRef} className={`${css.root} ${open ? css.isOpen : ''} ${variant === 'tile' ? css.tile : ''} ${className ?? ''}`}>
      <button
        type="button"
        id={id}
        role="combobox"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-label={ariaLabel}
        aria-activedescendant={open ? `${listId}-${active}` : undefined}
        disabled={disabled}
        className={css.trigger}
        onClick={() => (open ? setOpen(false) : openAt(selectedIndex))}
        onKeyDown={onKeyDown}
      >
        <span className={css.value}>{selected?.label}</span>
        <svg className={css.chevron} viewBox="0 0 24 24" fill="none" aria-hidden="true">
          <path d="M6 9l6 6 6-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      {createPortal(
      <ul
        ref={listRef}
        id={listId}
        role="listbox"
        aria-label={ariaLabel}
        className={`${css.list} ${open ? css.open : ''}`}
        style={place}
        tabIndex={-1}
      >
        {options.map((o, i) => (
          <li
            key={String(o.value)}
            id={`${listId}-${i}`}
            role="option"
            aria-selected={o.value === value}
            aria-disabled={o.disabled || undefined}
            className={`${css.option} ${i === active ? css.active : ''} ${o.value === value ? css.selected : ''}`}
            onPointerEnter={() => enabled(i) && setActive(i)}
            onPointerDown={(e) => e.preventDefault() /* keep focus on the button */}
            onClick={() => choose(i)}
          >
            <span>{o.label}</span>
            {o.value === value && (
              <svg viewBox="0 0 24 24" fill="none" aria-hidden="true" className={css.check}>
                <path d="M5 12.5l4.5 4.5L19 7.5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
          </li>
        ))}
      </ul>,
      document.body,
      )}
    </div>
  )
}
