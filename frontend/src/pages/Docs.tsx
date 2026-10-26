import { Link } from 'react-router-dom'

import LegalPage, { type LegalSection } from '../components/LegalPage'
import { REPO_URL } from '../lib/site'

// Product documentation (English, like the other public pages): how each part
// works and how to use it. The Home page's feature tiles link to these section
// ids. README.md and docs/ are the developer-facing versions of the same material.
const SECTIONS: LegalSection[] = [
  {
    id: 'start',
    title: 'Getting started',
    body: (
      <ol>
        <li>Sign up, then pick a username in Settings → Account.</li>
        <li>In Settings → Brand kit, set your voice, words to use or avoid, your logo, and your postal address (every marketing email shows it).</li>
        <li>On the Dashboard, describe the product and who it's for, add a photo of it (and, if you like, a tagline and a link), choose the audience's language, and start.</li>
        <li>CampaignIQ scores it, writes personas, makes a recommendation, and stops at <strong>Gate 1</strong>.</li>
        <li>After you approve, it designs and crash-tests the ad and stops at <strong>Gate 2</strong>. Approve, and it launches, measures and runs the next round.</li>
      </ol>
    ),
  },
  {
    id: 'gates',
    title: 'The two gates',
    body: (
      <>
        <p>
          <strong>Gate 1 (the idea)</strong> shows the feasibility score with its signals, the personas and the decision engine's
          recommendation. You can correct the market category (it trains the classifier), choose which persona leads, and pick who
          gets the email. Approving starts the creative; rejecting ends the campaign.
        </p>
        <p>
          <strong>Gate 2 (the ad)</strong> shows the finished ad, the compliance radar, the persona panel's reactions and the crash-test
          report. You can ask for a new picture, edit the copy (every version is kept, and a big change asks why), send yourself a test
          email, then approve. Nothing is posted or sent before this.
        </p>
      </>
    ),
  },
  {
    id: 'decision',
    title: 'Decision engine',
    body: (
      <>
        <p>
          Before any ad is made, the campaign gets a recommendation: <strong>launch</strong>, <strong>test small</strong>,{' '}
          <strong>wait</strong>, <strong>kill</strong>, or "not enough evidence". It weighs demand, momentum, purchase intent,
          competition, audience reach and your track record, and every factor shows where it came from, how fresh it is and how much to
          trust it.
        </p>
        <p>
          Prohibited products, claims nobody could back up and links that don't work are blocked outright. A "wait" comes with what to
          watch for; when that signal moves, the campaign is re-checked and you're told. You can approve against a recommendation, but
          you'll be asked why.
        </p>
      </>
    ),
  },
  {
    id: 'creative',
    title: 'Ads built around your product',
    body: (
      <p>
        Your product photo is cut out and set into one of <strong>34 layouts</strong>, drawn from a study of 128 real ads. The learning
        loop picks the layout family; the AI picks the layout that suits the product and writes its words from your idea only, never
        inventing reviews, prices or deadlines. Most backgrounds are drawn in code; a few have a scene painted around an empty spot. Your
        product itself is never repainted. At Gate 2, "New picture" makes another version.
      </p>
    ),
  },
  {
    id: 'crash-test',
    title: 'Crash test',
    body: (
      <p>
        Before Gate 2 every ad is checked for how it could fail. Rule checks catch invented testimonials, false urgency, fake social proof,
        questions about personal attributes and numbers you never gave. Eight simulated scenarios (a skeptic, a price-sensitive buyer, a
        competitor's discount and others) each quote the exact words that cause trouble. A revised version is re-tested on the same
        checks, and you can use it with one click.
      </p>
    ),
  },
  {
    id: 'loop',
    title: 'How it learns',
    body: (
      <>
        <p>
          A contextual bandit picks one of 20 image-style and copy-tone combinations for each round, using the persona's age and income,
          the channel and the market. Real clicks and engagement update it, so later rounds lean towards what worked for audiences like
          yours. A campaign runs up to 3 rounds on the free plan and 10 on Pro or with your own key, and stops early when it stops paying
          off.
        </p>
        <p>
          A fine-tuned model classifies each idea's market; your corrections at Gate 1 retrain it every week. Ads are also checked
          against your own past work so a new round doesn't repeat an old one.
        </p>
      </>
    ),
  },
  {
    id: 'email',
    title: 'Email to your own customers',
    body: (
      <>
        <p>
          Campaign email goes only to <strong>your own customers and subscribers who opted in</strong>, from{' '}
          <strong>your own Resend account</strong>. CampaignIQ never finds, scrapes or buys addresses.
        </p>
        <ol>
          <li>
            <strong>Connect</strong> (Settings → Email sending, owners and admins): create a free account at resend.com, ideally verify
            your domain there, and paste a full-access key. We use it once to install our bounce reports and create a sending-only key,
            and keep only that. Without a verified domain you can still try everything in <em>sandbox mode</em>: every email comes to
            your own inbox, labelled.
          </li>
          <li>
            <strong>Add contacts</strong> (Contacts): import a CSV, saying where people opted in; share your sign-up form (each person
            confirms by email, and your campaign posts link to it); or use the API.
          </li>
          <li>
            <strong>Choose who gets it</strong>: build segments by tag, purchases or country; at Gate 1 pick one, or use the AI's
            suggestion (it only ever sees group names and counts).
          </li>
          <li>
            <strong>Send</strong>: the audience is fixed when Gate 1 is approved, and each round emails the next batch. Nobody gets the
            same campaign twice, sending stays inside your sending window and daily limit, and the rest waits for the next slot.
          </li>
        </ol>
        <p>
          Every email greets the person, says why they're getting it, carries an unsubscribe link and Gmail's one-click unsubscribe, and
          shows your postal address. Bounces and spam complaints remove the address for good, and if they climb towards Resend's limits,
          sending pauses until an owner or admin resumes it. People who don't click or buy for 24 months stop getting email.
        </p>
      </>
    ),
  },
  {
    id: 'impact',
    title: 'Proof of impact',
    body: (
      <p>
        Declare an experiment on a campaign and a random share of its email audience is held back and gets nothing. Each emailed person's
        link carries a token, your site reports conversions through the API (or by email address), and at the end the report gives the
        lift the campaign caused with a 95% interval. When the evidence is thin it says "inconclusive" instead of guessing. Clicks and
        attribution are shown separately, never as the causal number.
      </p>
    ),
  },
  {
    id: 'memory',
    title: 'Brand memory',
    body: (
      <p>
        Brand memory keeps the reasons behind your team's decisions: a big edit at Gate 2 asks why, rejected claims and finished
        experiments are suggested as lessons, and you can add your own (Brand memory page). Confirmed lessons are given to the AI as
        background when it writes personas and ads; they can only make it stricter, and safety rules always win. Each lesson has its
        evidence, its scope, a review date and an optional expiry; correct, retire or delete it any time.
      </p>
    ),
  },
  {
    id: 'competitors',
    title: 'Competitor intelligence',
    body: (
      <p>
        On the Competitors page, name your competitors and approve which public sources to watch: their pages, feed, news and Bluesky
        posts. CampaignIQ reports observed moves (offers, launches, messaging, themes) with quotes and sources, counts one story once,
        recommends whether to respond, monitor, differentiate or do nothing, and forecasts search interest in their market, checked later
        against what happened.
      </p>
    ),
  },
  {
    id: 'fatigue',
    title: 'Creative fatigue',
    body: (
      <p>
        After every round, click rates are compared against the ad's own fresh baseline. Fatigue is called only on a sustained,
        significant drop that the creative explains, not a bad day for the market. When it is, a refresh of whatever repeats most is
        proposed; it goes through every check and gate, and its effect is measured.
      </p>
    ),
  },
  {
    id: 'safety',
    title: 'Circuit breaker and stopping',
    body: (
      <p>
        A live campaign pauses itself the moment it becomes unsafe: its offer ended, its link died, its copy now breaks a brand rule, an
        approval lapsed, or crisis news hit its topic. The database refuses every send while it's held. Owners and admins see why, resume
        with a note, or mark a false alarm. "Stop campaign" ends it at once and cancels any emails still waiting.
      </p>
    ),
  },
  {
    id: 'teams',
    title: 'Teams, approvals and notifications',
    body: (
      <>
        <p>
          Create a team in Settings → Team and invite people by email. <strong>Owners</strong> and <strong>admins</strong> manage
          everything; <strong>marketers</strong> create and run campaigns; <strong>approvers</strong> decide gates;{' '}
          <strong>viewers</strong> read. Only owners, admins and marketers see contacts' addresses.
        </p>
        <p>
          The approval policy can require up to five approvals per gate, stop creators approving their own work, and set a deadline.
          Choose who hears about approvals: they're told in the app (the bell in the top bar), by email and on Slack. Overdue approvals,
          held campaigns and paused email go to owners and admins. Each person can turn the emails off from the bell.
        </p>
      </>
    ),
  },
  {
    id: 'brand',
    title: 'Brand kit and brand safety',
    body: (
      <p>
        The brand kit sets your voice, preferred and forbidden words, a sign-off added to every post and email, your colour, logo, postal
        address and privacy link. Copy with links to other sites, personal data, forbidden words or text too long for the channel is
        rewritten automatically and can never be sent; health, finance and fitness claims are flagged at Gate 2 and get a disclaimer.
      </p>
    ),
  },
  {
    id: 'measure',
    title: 'Results, A/B tests and history',
    body: (
      <p>
        Each campaign's Metrics page shows every round's engagement, email results (delivered, bounced, spam reports) and what the
        learning loop chose. Tick "A/B test emails" to send two versions to two halves of each batch; the winner is declared only when the
        difference is significant. Playbooks write up what worked per market after each campaign. The Calendar shows what went out, what's
        due and which gates are waiting; every campaign has a comment thread.
      </p>
    ),
  },
  {
    id: 'tools',
    title: 'Tools',
    body: (
      <p>
        The Tools page runs one part on its own, without a campaign: score an idea, write personas, make an ad image or ask "should we
        advertise?". Results are kept in Run history.
      </p>
    ),
  },
  {
    id: 'api',
    title: 'API, webhooks and MCP',
    body: (
      <>
        <p>
          Create an API key in Settings → API &amp; webhooks and call <code>/functions/v1/api/v1/…</code> with{' '}
          <code>Authorization: Bearer ciq_…</code>: start campaigns, read results, add or erase contacts, choose a campaign's email
          audience and report conversions. The full reference is <a href={`${REPO_URL}/blob/main/docs/openapi.yaml`}>docs/openapi.yaml</a>.
          Webhooks deliver any event to your HTTPS endpoint, signed with HMAC-SHA256.
        </p>
        <p>
          AI assistants such as Claude Desktop can use CampaignIQ through its MCP server: score ideas, write personas and creative, and
          read campaign results. See the <a href={`${REPO_URL}/blob/main/docs/REFERENCE.md#mcp-server`}>setup guide</a>.
        </p>
      </>
    ),
  },
  {
    id: 'plans',
    title: 'Plans and limits',
    body: (
      <p>
        Free organisations can start 3 campaigns a day (3 active at once), run 3 rounds each, have 5 members, keep 1,000 contacts and use
        a daily AI budget; Pro raises every limit and removes the contact cap. The Dashboard shows your usage. Owners upgrade in
        Settings → Plan &amp; billing.
      </p>
    ),
  },
  {
    id: 'privacy',
    title: 'Your data and your customers’ data',
    body: (
      <p>
        Download everything we store about you, or delete your account, in Settings → Privacy &amp; data. For your contacts, owners and
        admins can export everyone with their consent history or erase a person; people can also unsubscribe or delete their own details
        from any email. Details are in the <Link to="/privacy">privacy policy</Link>; service health is on the{' '}
        <Link to="/status">status page</Link>.
      </p>
    ),
  },
]

export default function Docs() {
  return (
    <LegalPage
      eyebrow="Documentation"
      title="Using CampaignIQ"
      updated="27 October 2026"
      intro={<p>How every part works and how to use it, from the first idea to the API.</p>}
      sections={SECTIONS}
    />
  )
}
