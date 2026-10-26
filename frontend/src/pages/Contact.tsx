import type { CSSProperties, FormEvent } from 'react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from '../lib/toast'
import PublicLayout from '../components/PublicLayout'
import { ArrowIcon } from '../components/PublicNav'
import { CONTACT_EMAIL, REPO_URL } from '../lib/site'
import styles from '../components/public.module.css'
import local from './Contact.module.css'

const TOPICS = ['General question', 'Feedback on the product', 'Bug report', 'Collaboration or hiring', 'Privacy request']

export default function Contact() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [topic, setTopic] = useState(TOPICS[0])
  const [message, setMessage] = useState('')
  const [opened, setOpened] = useState(false)

  // No backend stores this: it hands a prefilled draft to the visitor's own mail app.
  function onSubmit(e: FormEvent) {
    e.preventDefault()
    const subject = `[CampaignIQ] ${topic}`
    const body = `${message}\n\n— ${name}${email ? ` (${email})` : ''}`
    window.location.href = `mailto:${CONTACT_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`
    setOpened(true)
  }

  async function copyEmail() {
    try {
      await navigator.clipboard.writeText(CONTACT_EMAIL)
      toast.success('Email address copied.')
    } catch {
      // Clipboard blocked: the address is still on screen to copy by hand.
      toast.error("Couldn't copy. Select the address above and copy it by hand.")
    }
  }

  return (
    <PublicLayout>
      <section className={styles.enter}>
        <span className={styles.eyebrow}>Contact</span>
        <h1 className={styles.pageTitle}>
          Let’s <em>talk</em>.
        </h1>
        <p className={styles.lead}>
          Questions about how the loop works, feedback, a bug, or an idea for working together. Send a note and it goes
          straight to a person.
        </p>
      </section>

      <div className={local.layout}>
        <form className={`${styles.card} ${local.form} ${styles.enter}`} style={{ '--i': 2 } as CSSProperties} onSubmit={onSubmit}>
          <div className={local.row}>
            <label className={local.field}>
              <span>Your name</span>
              <input required value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" placeholder="Ada Lovelace" />
            </label>
            <label className={local.field}>
              <span>Your email</span>
              <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" placeholder="you@company.com" />
            </label>
          </div>
          <div className={local.field}>
            <span>What’s it about?</span>
            <div className={local.topics} role="radiogroup" aria-label="Topic">
              {TOPICS.map((t) => (
                <button
                  key={t}
                  type="button"
                  role="radio"
                  aria-checked={topic === t}
                  className={`${local.topic} ${topic === t ? local.topicActive : ''}`}
                  onClick={() => setTopic(t)}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
          <label className={local.field}>
            <span>Message</span>
            <textarea required rows={6} value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Tell us a little about what you need…" maxLength={2000} />
            <small className={local.count}>{message.length} / 2000</small>
          </label>
          <div className={local.formFoot}>
            <p className={local.note}>Opens your email app with this message ready to send. Nothing is stored on our side.</p>
            <button type="submit" className={`${styles.btn} ${styles.btnPrimary}`}>
              Send message
              <ArrowIcon className={styles.arrow} />
            </button>
          </div>
          {opened && (
            <p className={local.sent} role="status">
              Your email app should have opened with the message. If it didn’t, write to {CONTACT_EMAIL} directly.
            </p>
          )}
        </form>

        <aside className={local.side}>
          <div className={`${styles.card} ${styles.enter}`} style={{ '--i': 3 } as CSSProperties}>
            <span className={styles.cardKicker}>Email</span>
            <h3 className={local.email}>{CONTACT_EMAIL}</h3>
            <div className={local.actions}>
              <a className="link-wipe" href={`mailto:${CONTACT_EMAIL}`}>
                Write an email
              </a>
              <button type="button" className={local.copy} onClick={copyEmail}>
                Copy address
              </button>
            </div>
          </div>
          <div className={`${styles.card} ${styles.enter}`} style={{ '--i': 4 } as CSSProperties}>
            <span className={styles.cardKicker}>Found a bug?</span>
            <h3>Open an issue on GitHub</h3>
            <p>Steps to reproduce and a screenshot help the most.</p>
            <a className={`link-wipe ${local.inlineLink}`} href={`${REPO_URL}/issues`} target="_blank" rel="noopener noreferrer">
              Go to issues →
            </a>
          </div>
          <div className={`${styles.card} ${styles.enter}`} style={{ '--i': 5 } as CSSProperties}>
            <span className={styles.cardKicker}>Before you write</span>
            <h3>Quick answers</h3>
            <p>Pricing, privacy and how the loop works are covered elsewhere.</p>
            <div className={local.quick}>
              <Link className="link-wipe" to="/#faq">FAQ</Link>
              <Link className="link-wipe" to="/#pricing">Pricing</Link>
              <Link className="link-wipe" to="/privacy">Privacy</Link>
            </div>
          </div>
        </aside>
      </div>
    </PublicLayout>
  )
}
