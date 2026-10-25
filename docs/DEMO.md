# MarketingOS demo script

A 10-minute walkthrough for the project submission: one campaign from idea to
learning loop, then the parts that make it more than "an app that calls an
LLM". Screenshots of each stop are in [docs/screenshots](screenshots).

## The day before

Work through this list once, a day ahead, so nothing is first-time on stage.

**Backend**
- [ ] Code pushed to `main`, and the cloud database migrated (`supabase db push`), including `20261024000100_ad_images` and `20261024000200_ad_copy_and_logos`.
- [ ] GitHub secrets set: `GROQ_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, `BLUESKY_*`, `MASTODON_POST_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN`.
- [ ] Secret `DRY_RUN` = `false` (otherwise nothing is really posted or emailed).
- [ ] OpenAI images: only if you want them for the demo, set the repo **variable** `OPENAI_IMAGE_GEN` = `on`, the secret `OPENAI_API_KEY`, and make sure the OpenAI account has credit. Otherwise leave it off: Cloudflare FLUX is the default.
- [ ] Edge Function secret `GROQ_API_KEY` set (persona interviews).

**A showcase campaign, run in advance.** A live campaign takes a few minutes per stage plus the metrics wait, so run one the day before and present it; start a second one live only for Gates 1 and 2.
- [ ] Brand kit filled in (Settings → Brand kit): voice, a forbidden word, a sign-off, brand colour, **logo**.
- [ ] Campaign idea (example): *"Order-ahead coffee for commuters: skip the morning queue"* (it posts to Bluesky and Mastodon and emails the list), email A/B test on, your own address plus one or two friends as recipients, CTA link to any page you own. Have a **product photo** ready (required; a plain background cuts out best) and, optionally, a tagline.
- [ ] Approve Gate 1, look at the Gate 2 ad, try **New picture** once, approve.
- [ ] Next morning: check the Bluesky and Mastodon posts and the email (the ad is inside it), then the metrics page.

**On the laptop**
- [ ] Signed in on the deployed site, browser zoom 100 %, notifications off.
- [ ] Tabs open: Dashboard, the showcase campaign, Playbooks, Our AI model, the Bluesky post, the Mastodon post, the email.
- [ ] A backup: the screenshots in `docs/screenshots` (and a screen recording, if you make one) in case the network fails.

## The walkthrough (about 10 minutes)

| Time | Where | What to show | What to say |
|---|---|---|---|
| 0:00 | Dashboard | The composer, market moments, "waiting for approval" | "You type one idea. Everything else is agents, with a human at two gates." |
| 0:45 | New campaign | Type the idea, add the product photo, tagline and link, create | "Every ad is built around the real product: it is cut out and set into one of 34 templates from real brand ads. Feasibility uses real signals: search trends and community chatter, not just an LLM's opinion." |
| 1:30 | Campaign → Gate 1 | Feasibility score, the three 3D personas, category | "The category came from our own fine-tuned model. If I correct it here, that correction trains the next version." |
| 2:30 | Persona card → Interview | Ask *"What price feels fair?"* | "Each persona answers in character, from its own profile. A quick gut check before spending money." |
| 3:30 | Showcase campaign → Gate 2 | The finished ad, headline and button beside it | "The picture is FLUX; the words are set by us, so they're always legible and on-brand, with the logo." |
| 4:15 | Gate 2 | Press **New picture** (or show one made earlier) | "Approvers stay in control of the image without the copy being rewritten. Five repaints per round." |
| 4:45 | Gate 2 | Compliance radar, audience verdict | "Brand safety, claims, readability and accessibility are checked before anyone approves. The focus group is our personas reacting to the actual ad." |
| 5:30 | Rounds → Why this ad? | The bandit explanation | "Each ad is one of 20 style × tone arms. A contextual bandit (LinUCB) picks it, and explains why: exploit or explore." |
| 6:15 | Bluesky + Mastodon posts + email | The real posts and the email with the ad inside | "Same finished ad on every channel. Email is A/B tested: two variants, two halves of the list." |
| 7:00 | Metrics | Rewards, the Bayesian A/B result | "When one variant is 95 % likely to be better, the test stops early and the winner's arm is promoted." |
| 8:00 | Playbooks | The industry playbook | "After each campaign the system writes down what worked, and the next campaign's copy reads it." |
| 8:45 | Our AI model | Model card, versions, shadow agreement | "Our own 1.5B model, fine-tuned and quantised to run on a CPU. It runs in shadow first and only takes over when it agrees enough." |
| 9:30 | Wrap-up | Back to the dashboard | "Idea → research → personas → ad → human approval → posting → measuring → learning, on free tiers." |

## If something goes wrong on stage

- **A stage is slow** (GitHub Actions queueing): switch to the showcase campaign, which is already past that point.
- **Image provider is out of quota:** the app falls back on its own (Cloudflare → Hugging Face → Gemini → Pollinations); say so. That is a feature.
- **No network:** walk through `docs/screenshots` and the README instead.
- **A gate needs a second approver:** the approval policy may require several; approve from a second account or lower it in Settings → Team → Approvals.

## Likely questions

- **"Isn't this just ChatGPT with extra steps?"** The decisions that matter are made by things we trained or built: our fine-tuned classifier, the bandit, the Bayesian A/B test, the guardrails and the ad layout. The LLM writes words; the system decides, measures and learns.
- **"Are the testimonials and urgency real?"** The layouts never invent ratings, reviews or deadlines; the guardrails flag unsupported claims for a human to check.
- **"What does it cost to run?"** Free tiers by default: Groq for text, Cloudflare FLUX for images, GitHub Actions for workers, Supabase. Paid keys (OpenAI, bring your own) are optional.
- **"How is data protected?"** Row-level security per organisation and role, private storage buckets, an audit log, data export and account deletion (Settings → Privacy).
