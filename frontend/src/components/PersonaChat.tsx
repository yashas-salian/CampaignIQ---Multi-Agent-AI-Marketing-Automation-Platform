import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'

import { archetypeFor, genderFor } from '../lib/archetypes'
import { toastFailure } from '../lib/notify'
import { supabase } from '../lib/supabaseClient'
import css from './PersonaChat.module.css'

export type ChatTarget =
  | { kind: 'persona'; id: string }
  | { kind: 'run'; runId: string; index: number }

interface Message {
  role: 'user' | 'assistant'
  content: string
}

const SUGGESTED = ['price', 'ignore', 'trust', 'where', 'switch'] as const

/** Interview one persona: it answers in character, grounded in its profile and the campaign idea. */
export default function PersonaChat({
  target,
  persona,
  onClose,
}: {
  target: ChatTarget
  persona: { name: string; archetype?: unknown; gender?: unknown; demographics?: unknown; psychographics?: unknown }
  onClose: () => void
}) {
  const { t } = useTranslation()
  const ref = target.kind === 'persona' ? `persona:${target.id}` : `run:${target.runId}:${target.index}`
  const [messages, setMessages] = useState<Message[]>([])
  const [draft, setDraft] = useState('')
  const [thinking, setThinking] = useState(false)
  const [remaining, setRemaining] = useState<number | null>(null)
  const log = useRef<HTMLOListElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const dialog = useRef<HTMLDivElement>(null)

  const kind = archetypeFor(persona.archetype, persona.name, persona.demographics)
  const sex = genderFor(persona.gender, persona.demographics, persona.psychographics)

  // Earlier questions to this persona (kept per person, private to them).
  useEffect(() => {
    supabase
      .from('persona_chats')
      .select('role,content')
      .eq('persona_ref', ref)
      .order('created_at')
      .then(({ data, error }) => {
        if (!toastFailure(t, error)) setMessages((data as Message[]) ?? [])
      })
  }, [ref, t])

  useEffect(() => {
    log.current?.lastElementChild?.scrollIntoView({ block: 'end', behavior: 'smooth' })
  }, [messages, thinking])

  // A dialog: Esc closes, focus starts in the question box and stays inside.
  useEffect(() => {
    input.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key !== 'Tab' || !dialog.current) return
      const focusable = dialog.current.querySelectorAll<HTMLElement>('button:not([disabled]), textarea')
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const ask = useCallback(
    async (question: string) => {
      const q = question.trim()
      if (!q || thinking) return
      setDraft('')
      setMessages((m) => [...m, { role: 'user', content: q }])
      setThinking(true)
      const body = target.kind === 'persona' ? { persona_id: target.id, question: q } : { run_id: target.runId, index: target.index, question: q }
      const { data, error, response } = await supabase.functions.invoke('persona-chat', { body })
      setThinking(false)
      if (error) {
        const reason = response ? ((await response.json().catch(() => null)) as { error?: string; remaining?: number } | null) : null
        if (typeof reason?.remaining === 'number') setRemaining(reason.remaining)
        toastFailure(t, reason?.error ?? error.message)
        // Put the question back so it isn't lost.
        setMessages((m) => m.slice(0, -1))
        setDraft(q)
        return
      }
      setMessages((m) => [...m, { role: 'assistant', content: (data as { answer: string }).answer }])
      setRemaining((data as { remaining: number }).remaining)
    },
    [target, thinking, t],
  )

  function submit(e: FormEvent) {
    e.preventDefault()
    ask(draft)
  }

  return (
    <div className={css.backdrop} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={dialog} className={css.dialog} role="dialog" aria-modal="true" aria-label={t('chat.title', { name: persona.name })}>
        <header className={css.head}>
          {sex === 'unspecified' ? (
            <span className={css.avatar} aria-hidden="true">{persona.name.slice(0, 1)}</span>
          ) : (
            <img className={css.avatar} src={`/personas/${kind}-${sex}.webp`} alt="" />
          )}
          <div className={css.who}>
            <strong>{t('chat.title', { name: persona.name })}</strong>
            <span>{t(`persona.${kind}`)} · {t('chat.inCharacter')}</span>
          </div>
          <button type="button" className={css.close} onClick={onClose} aria-label={t('drawer.close')}>
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
          </button>
        </header>

        <ol ref={log} className={css.log} aria-live="polite">
          {messages.length === 0 && !thinking && <li className={css.intro}>{t('chat.intro', { name: persona.name })}</li>}
          {messages.map((m, i) => (
            <li key={i} className={m.role === 'user' ? css.mine : css.theirs}>
              {m.content}
            </li>
          ))}
          {thinking && (
            <li className={`${css.theirs} ${css.typing}`} aria-label={t('chat.thinking', { name: persona.name })}>
              <span />
              <span />
              <span />
            </li>
          )}
        </ol>

        <div className={css.suggest}>
          {SUGGESTED.map((s) => (
            <button key={s} type="button" disabled={thinking} onClick={() => ask(t(`chat.q_${s}`))}>
              {t(`chat.q_${s}`)}
            </button>
          ))}
        </div>

        <form className={css.form} onSubmit={submit}>
          <textarea
            ref={input}
            value={draft}
            maxLength={500}
            rows={2}
            placeholder={t('chat.placeholder', { name: persona.name })}
            aria-label={t('chat.placeholder', { name: persona.name })}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                ask(draft)
              }
            }}
          />
          <button type="submit" disabled={thinking || !draft.trim()} aria-label={t('chat.send')}>
            <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path d="M4 12l16-8-6 16-2-7z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
            </svg>
          </button>
        </form>
        <p className={css.foot}>
          {remaining !== null ? t('chat.remaining', { count: remaining }) : t('chat.note')}
        </p>
      </div>
    </div>
  )
}
