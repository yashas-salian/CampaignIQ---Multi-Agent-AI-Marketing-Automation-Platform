import { Link } from 'react-router-dom'

import LegalPage, { type LegalSection } from '../components/LegalPage'
import { REPO_URL } from '../lib/site'

// Product documentation (English, like the other public pages). Keep it in step
// with README.md, which is the developer-facing version of the same material.
const SECTIONS: LegalSection[] = [
  {
    id: 'start',
    title: 'Getting started',
    body: (
      <ol>
        <li>Sign up, then pick a username in Settings → Account.</li>
        <li>On the Dashboard, describe a product and who it's for, choose the audience language, and start the campaign.</li>
        <li>MarketingOS scores feasibility from live signals, writes personas, and stops at <strong>Gate 1</strong> for you to check the category and persona.</li>
        <li>It writes the creative, pre-tests it on a synthetic panel, and stops at <strong>Gate 2</strong>. Edit the copy if you like, then approve.</li>
        <li>It posts and emails, waits for engagement, learns, and runs the next round until it stops paying off or hits your plan's round cap.</li>
      </ol>
    ),
  },
  {
    id: 'loop',
    title: 'How the loop decides',
    body: (
      <>
        <p>
          A contextual bandit (LinUCB) picks one of 20 image-style × copy-tone combinations for each round, using the persona's age and
          income, the channel and the product category. Every round's real engagement updates it, so later rounds lean towards what has
          actually worked for audiences like yours.
        </p>
        <p>
          Feasibility combines Google Trends interest, news volume and community activity; the rationale explains the signals. A
          fine-tuned classifier picks the category on the free tier, and your Gate 1 corrections retrain it every week.
        </p>
      </>
    ),
  },
  {
    id: 'teams',
    title: 'Teams, roles and approvals',
    body: (
      <>
        <p>
          Create a team organisation in Settings → Team and invite people by email. Roles: <strong>owner</strong> and{' '}
          <strong>admin</strong> manage everything; <strong>marketers</strong> create and run campaigns; <strong>approvers</strong>{' '}
          decide gates; <strong>viewers</strong> read. Marketers can't approve their own campaigns.
        </p>
        <p>
          In the approval policy you can require up to five approvals per gate, stop creators approving their own work, set an approval
          deadline (overdue gates are escalated to owners and admins) and send notifications to Slack.
        </p>
      </>
    ),
  },
  {
    id: 'brand',
    title: 'Brand kit and brand safety',
    body: (
      <p>
        The brand kit (Settings → Brand kit) sets your voice, preferred and forbidden words and a sign-off that's added to every post and
        email. Copy with links to other sites, personal data, forbidden words or text too long for Bluesky is rewritten automatically and
        can never be sent; health, finance and fitness claims are flagged at Gate 2 and get a disclaimer.
      </p>
    ),
  },
  {
    id: 'ab',
    title: 'A/B testing emails',
    body: (
      <p>
        Tick “A/B test emails” when you start a campaign. Each round then writes a second variant with a different style; your recipient
        list is split in half, each half gets one variant, and the Metrics page tells you which one wins once the difference is
        statistically significant (p &lt; 0.05).
      </p>
    ),
  },
  {
    id: 'calendar',
    title: 'Calendar, comments and history',
    body: (
      <p>
        The Calendar shows what went out, what's due and which gates are waiting. Every campaign has a discussion thread, and every edit to
        approved copy is kept as a version you can restore. Owners and admins can see the full audit log in Settings and export it.
      </p>
    ),
  },
  {
    id: 'api',
    title: 'API, webhooks and MCP',
    body: (
      <>
        <p>
          Create an API key in Settings → API &amp; webhooks and call <code>/functions/v1/api/v1/campaigns</code> with{' '}
          <code>Authorization: Bearer mos_…</code>. The full reference is <a href={`${REPO_URL}/blob/main/docs/openapi.yaml`}>docs/openapi.yaml</a>.
          Webhooks deliver any event to your HTTPS endpoint, signed with HMAC-SHA256.
        </p>
        <p>
          AI assistants such as Claude Desktop can use MarketingOS directly through its MCP server: score ideas, write personas and
          creative, and read campaign results. See the <a href={`${REPO_URL}#mcp-server-m8`}>setup guide</a>.
        </p>
      </>
    ),
  },
  {
    id: 'plans',
    title: 'Plans and limits',
    body: (
      <p>
        Free organisations can start 3 campaigns a day (3 active at once), have 5 members and use a daily AI budget; Pro raises every
        limit. The Dashboard shows your usage. Owners upgrade in Settings → Plan &amp; billing.
      </p>
    ),
  },
  {
    id: 'privacy',
    title: 'Your data',
    body: (
      <p>
        Download everything we store about you, or delete your account, in Settings → Privacy &amp; data. Details are in the{' '}
        <Link to="/privacy">privacy policy</Link>; service health is on the <Link to="/status">status page</Link>.
      </p>
    ),
  },
]

export default function Docs() {
  return (
    <LegalPage
      eyebrow="Documentation"
      title="Using MarketingOS"
      updated="22 October 2026"
      intro={<p>Everything you need to run campaigns with your team, from the first idea to the API.</p>}
      sections={SECTIONS}
    />
  )
}
