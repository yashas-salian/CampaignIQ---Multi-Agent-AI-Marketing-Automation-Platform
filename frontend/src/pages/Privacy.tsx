import { Link } from 'react-router-dom'
import LegalPage, { type LegalSection } from '../components/LegalPage'
import { CONTACT_EMAIL } from '../lib/site'

// Describes what this codebase actually stores and sends; keep it in step with
// src/db/*.sql and the providers/tools when either changes.
const SECTIONS: LegalSection[] = [
  {
    id: 'collect',
    title: 'What we collect',
    body: (
      <ul>
        <li>
          <strong>Account:</strong> your email address and sign-in method (password, Google or GitHub), handled by
          Supabase Auth. Passwords are stored only as hashes.
        </li>
        <li>
          <strong>Campaigns:</strong> the ideas you enter, the target language, generated personas, copy and image
          prompts, your gate decisions and comments, and any email recipients you provide.
        </li>
        <li>
          <strong>Results:</strong> engagement counts for each round (likes, reposts, replies, link clicks) and the
          reward computed from them.
        </li>
        <li>
          <strong>Your API keys (optional):</strong> encrypted with AES-256-GCM before they are stored. Only the last
          four characters are ever shown back to you.
        </li>
        <li>
          <strong>Templates (optional):</strong> an ad image or email layout you upload.
        </li>
      </ul>
    ),
  },
  {
    id: 'use',
    title: 'How it’s used',
    body: (
      <>
        <p>
          Your data is used to run your campaigns: scoring ideas, generating creative, posting and emailing, and
          measuring results. It is not sold and not used for advertising.
        </p>
        <p>
          A shared learning model (the bandit) stores only abstract statistics, such as which style and tone worked
          in a product category. It never stores your campaign text, and other users never see your content.
        </p>
      </>
    ),
  },
  {
    id: 'third-parties',
    title: 'Services we send data to',
    body: (
      <ul>
        <li>
          <strong>Supabase</strong> stores the database and handles sign-in.
        </li>
        <li>
          <strong>Groq, or OpenAI</strong> (when you or the platform use a paid key) receives idea text and prompts to
          generate scores, personas and copy.
        </li>
        <li>
          <strong>Pollinations or OpenAI</strong> receives image prompts.
        </li>
        <li>
          <strong>Google Trends, NewsAPI, Bluesky and Mastodon search</strong> receive short keyword phrases to measure
          market interest.
        </li>
        <li>
          <strong>Bluesky</strong> publishes approved posts from a shared platform account, and <strong>Resend</strong>{' '}
          delivers approved emails.
        </li>
        <li>
          <strong>GitHub Actions</strong> runs the background workers that process your campaigns.
        </li>
      </ul>
    ),
  },
  {
    id: 'isolation',
    title: 'Who can see your data',
    body: (
      <p>
        Every table that holds your data is protected by Postgres row-level security, so the database itself refuses
        requests for rows that aren’t yours. Posts you approve at Gate 2 are public on Bluesky once published.
      </p>
    ),
  },
  {
    id: 'retention',
    title: 'Keeping and deleting data',
    body: (
      <p>
        Data is kept while your account exists. To delete your account and everything linked to it, email{' '}
        <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>. Deleting an account removes its campaigns, results,
        keys and templates. Posts already published on Bluesky must be removed there separately.
      </p>
    ),
  },
  {
    id: 'cookies',
    title: 'Cookies and local storage',
    body: (
      <p>
        The app uses your browser’s local storage for your sign-in session and your theme and language choices. There
        are no advertising or tracking cookies. Email links pass through our own click redirect so campaign clicks can
        be counted.
      </p>
    ),
  },
  {
    id: 'contact',
    title: 'Questions',
    body: (
      <p>
        Ask anything about your data on the <Link to="/contact">contact page</Link> or at{' '}
        <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>. The rules for using the service are in the{' '}
        <Link to="/terms">terms of use</Link>.
      </p>
    ),
  },
]

export default function Privacy() {
  return (
    <LegalPage
      eyebrow="Privacy"
      title="Privacy policy"
      updated="20 October 2026"
      intro={
        <>
          MarketingOS is a portfolio project. This page explains plainly what the app stores and where it goes. It is
          not legal advice.
        </>
      }
      sections={SECTIONS}
    />
  )
}
