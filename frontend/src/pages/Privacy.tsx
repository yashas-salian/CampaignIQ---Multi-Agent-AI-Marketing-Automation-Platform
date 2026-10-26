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
          <strong>Campaigns:</strong> the ideas and product photos you enter, the target language, generated personas,
          ads and copy, your gate decisions and comments.
        </li>
        <li>
          <strong>Results:</strong> engagement counts for each round (likes, reposts, replies, link clicks) and the
          reward computed from them.
        </li>
        <li>
          <strong>Your keys (optional):</strong> model-provider keys and your Resend sending key are kept in Supabase
          Vault, readable only by the background workers. Only the last four characters are ever shown back to you.
        </li>
        <li>
          <strong>Templates (optional):</strong> an ad image or email layout you upload.
        </li>
        <li>
          <strong>Your contacts:</strong> the customers and subscribers your organisation adds for email (see{' '}
          <a href="#contacts">your customers' data</a>).
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
          <strong>Groq</strong> (with Cerebras, OpenRouter or Gemini as fallbacks), or <strong>OpenAI</strong> when you
          or the platform use a paid key, receives idea text and prompts to generate scores, personas and copy. None of
          them receives your contacts' addresses or names.
        </li>
        <li>
          <strong>Cloudflare or Hugging Face</strong> (FLUX), with <strong>Gemini</strong> or <strong>Pollinations</strong>{' '}
          as fallbacks, receives prompts for ad backgrounds; your product photo is cut out on our own workers and never sent
          to them.
        </li>
        <li>
          <strong>Google Trends, NewsAPI, Bluesky and Mastodon search</strong> receive short keyword phrases to measure
          market interest.
        </li>
        <li>
          <strong>Bluesky</strong> and, where the operator has switched it on, <strong>Mastodon</strong> publish approved
          posts from a shared platform account. <strong>Resend</strong> delivers campaign emails through your own
          organisation's Resend account, and the app's notification emails through ours.
        </li>
        <li>
          <strong>GitHub Actions</strong> runs the background workers that process your campaigns.
        </li>
        <li>
          <strong>Stripe</strong> handles payment for paid plans; we never see your card details.
        </li>
      </ul>
    ),
  },
  {
    id: 'contacts',
    title: 'Your customers’ data',
    body: (
      <>
        <p>
          When your organisation emails its own customers, it decides who they are and why it may email them; CampaignIQ
          stores and sends on its behalf. For each contact we keep their email address, name and language if given, the tags
          and purchase details your organisation adds, and a <strong>consent record</strong>: where and when they agreed,
          and the exact wording. Every change is logged.
        </p>
        <p>
          Only your organisation's owners, admins and marketers can see contacts' addresses, and no other organisation can
          see them at all. The AI never receives a contact's address or name: to suggest an audience it sees only group
          names and counts.
        </p>
        <p>
          Every campaign email has an unsubscribe link. From it, a person can also delete their details. Owners and admins
          can export everyone or erase a person. After an unsubscribe, bounce, spam complaint or erasure, only a one-way hash
          of the address is kept, so the person is never added or emailed again. Links in campaign emails are tracked per
          person so the brand knows what interests them, and each email says so.
        </p>
      </>
    ),
  },
  {
    id: 'isolation',
    title: 'Who can see your data',
    body: (
      <p>
        Every table that holds your data is protected by Postgres row-level security, so the database itself refuses
        requests for rows that aren’t yours. Posts you approve at Gate 2 are public on Bluesky (and Mastodon, when switched on) once published.
      </p>
    ),
  },
  {
    id: 'retention',
    title: 'Keeping and deleting data',
    body: (
      <>
        <p>
          <strong>Download or delete it yourself:</strong> Settings → Privacy &amp; data. The download is a JSON file
          with your account, the campaigns you created with their results, your votes and corrections, templates,
          masked API keys, Tools runs, AI usage and private memory. Deleting your account removes all of it, including
          your stored API keys and the category corrections future classifier training would use. Campaigns you created
          inside a team organisation belong to that team and stay with it. Posts already published on Bluesky or Mastodon must be
          removed there separately. Questions: <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
        </p>
        <p>
          <strong>How long we keep things:</strong> your data stays while your account exists. Some operational data is
          pruned automatically: Tools results after 90 days, per-request AI usage after 180 days, the recipient list and
          content of delivered emails after 30 days, and raw click events after a year. A security audit log of account
          and team actions is kept; it refers to people only by an internal id. Contacts are kept until your organisation
          or the person removes them; a contact with no click or purchase for 24 months is no longer emailed.
        </p>
      </>
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
      updated="27 October 2026"
      intro={
        <>
          CampaignIQ is a portfolio project. This page explains plainly what the app stores and where it goes. It is
          not legal advice.
        </>
      }
      sections={SECTIONS}
    />
  )
}
