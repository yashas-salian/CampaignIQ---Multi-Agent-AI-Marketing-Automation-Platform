import { Link } from 'react-router-dom'
import LegalPage, { type LegalSection } from '../components/LegalPage'
import { CONTACT_EMAIL, CONTACT_EMAIL_TEXT } from '../lib/site'

const SECTIONS: LegalSection[] = [
  {
    id: 'service',
    title: 'The service',
    body: (
      <p>
        CampaignIQ helps you research, create, publish and measure ad campaigns. It is offered as a portfolio
        project, as is, without guarantees of availability or results.
      </p>
    ),
  },
  {
    id: 'account',
    title: 'Your account',
    body: (
      <p>
        Keep your sign-in details private. You are responsible for activity on your account, including the campaigns
        you approve.
      </p>
    ),
  },
  {
    id: 'content',
    title: 'What you may publish',
    body: (
      <>
        <p>
          Campaigns are published only after you approve them at Gate 2, and they go out from a shared platform
          account. Don’t use the service for:
        </p>
        <ul>
          <li>spam, or email to people who haven’t agreed to hear from you;</li>
          <li>misleading, unlawful, hateful or harassing content;</li>
          <li>content that infringes someone else’s rights.</li>
        </ul>
        <p>Campaigns that break these rules may be stopped and accounts suspended.</p>
      </>
    ),
  },
  {
    id: 'keys',
    title: 'Your own API keys',
    body: (
      <p>
        If you add your own provider key, calls made with it are billed to your provider account under that provider’s
        terms. A key that fails is reported as an error rather than silently switched to another tier.
      </p>
    ),
  },
  {
    id: 'email',
    title: 'Emailing your customers',
    body: (
      <p>
        You may only add people to your contacts who agreed to receive marketing email from your organisation, and you're
        responsible for that consent and for the postal address and privacy link your emails show. Never import bought,
        rented or scraped lists. Campaign emails go through your own Resend account under its terms. Sending pauses
        automatically when bounces or spam complaints near Resend's limits, and we may suspend email for an organisation
        that misuses it.
      </p>
    ),
  },
  {
    id: 'billing',
    title: 'Plans and billing',
    body: (
      <p>
        There are three plans: Free, Pro and Bring your own key. Pro is billed through Stripe Checkout, and cards and
        invoices are managed in Stripe's customer portal. <strong>As a portfolio project, the service runs Stripe in test
        mode:</strong> no real payments are taken.
      </p>
    ),
  },
  {
    id: 'liability',
    title: 'Limits',
    body: (
      <p>
        Feasibility scores and generated creative are estimates, not advice. To the extent the law allows, the service
        is not liable for campaign outcomes or third-party service outages.
      </p>
    ),
  },
  {
    id: 'changes',
    title: 'Changes and contact',
    body: (
      <p>
        These terms may change as the project evolves; the date above shows the latest version. Questions go to the{' '}
        <Link to="/contact">contact page</Link> or <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL_TEXT}</a>. See also
        the <Link to="/privacy">privacy policy</Link>.
      </p>
    ),
  },
]

export default function Terms() {
  return (
    <LegalPage
      eyebrow="Terms"
      title="Terms of use"
      updated="27 October 2026"
      intro={<>CampaignIQ is a portfolio project. These terms are written in plain language and are not legal advice.</>}
      sections={SECTIONS}
    />
  )
}
