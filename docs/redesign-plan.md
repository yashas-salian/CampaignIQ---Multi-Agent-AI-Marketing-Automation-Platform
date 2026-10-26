# Frontend redesign plan ("Signal")

An original design system for CampaignIQ. It takes the *kind* of motion
common to modern SaaS marketing sites (scroll reveals, hover lifts,
marquees, sticky sections) but uses its own palette, type, layout and copy.

## 1. Design tokens (`frontend/src/index.css`)

Names stay `--ciq-*` so every app page picks the new look up for free.

| Token | Dark (default) | Light |
|---|---|---|
| `--ciq-bg` | `#0c0e10` | `#f7f6f3` |
| `--ciq-bg-raised` | `#12151a` | `#efede8` |
| `--ciq-surface` | `#161a20` | `#ffffff` |
| `--ciq-surface-border` | `#242a33` | `#e2dfd8` |
| `--ciq-text` / `-muted` | `#edf1f5` / `#8d97a5` | `#111316` / `#5f6672` |
| `--ciq-accent` (signal orange) | `#ff6b3d` | `#e4521f` |
| `--ciq-success` / `--ciq-danger` | `#3ecf8e` / `#ff5470` | `#16a36a` / `#e0364f` |

Type: Space Grotesk (display), Inter (body), JetBrains Mono (labels, data),
loaded from Google Fonts. Radius 18px for cards, pills for buttons.

## 2. Motion system

| Effect | Where | Spec |
|---|---|---|
| Reveal | every section head, card | fade + 24px rise + 6px blur → 0, 0.8s `cubic-bezier(.16,1,.3,1)`, children stagger 80ms |
| Word rise | hero headline | each word slides up out of a mask, 60ms stagger |
| Hide-on-scroll nav | floating pill nav | slides up when scrolling down, back on scroll up |
| Hero media parallax | video placeholder | scales 0.9 → 1 and un-rounds as it scrolls into view |
| Marquee | channel / stack band | two rows, opposite directions, 38s loop, pause on hover, edge fade |
| Count-up | stats row | numbers count from 0 when revealed, 1.4s ease-out |
| Sticky step panel | "The loop" | left panel pins; big step number + progress bar follow the active card on the right |
| Stacking cards | three differentiators | cards pin at staggered offsets and shrink slightly as the next one covers them |
| Hover lift + spotlight | bento tiles, pricing | lift 6px, cursor-following radial glow on the border |
| Button hover | all CTAs | arrow slides right, primary gains glow; text links underline grows from the left |
| Accordion | FAQ | smooth height + rotating plus icon |

All of it switches off under `prefers-reduced-motion`.

## 3. Page mapping

| Page | Treatment |
|---|---|
| Landing `/` | nav → hero + media placeholder → marquee → stats → sticky loop → stacking differentiators → bento proof → pricing → FAQ → CTA → footer with oversized wordmark |
| Login | centered card on the new background, same buttons/inputs |
| Dashboard, CampaignDetail, Metrics, Tools, Settings | new tokens via `shell.module.css`; sticky blurred top bar; cards lift on hover |

## 4. Phases

1. Tokens, fonts, Landing (this change).
2. App shell: top bar, cards, inputs, Login layout.
3. QA: light/dark, mobile (375px), reduced motion, `npm run build` + `npm run lint`.

Media: image and video slots are placeholders until real assets exist.
