/**
 * Photos used on the marketing pages. All are free under the Unsplash License
 * (https://unsplash.com/license): commercial use allowed, no permission needed.
 * Credit isn't required but is shown anyway. Each was picked for what its
 * placement says, not for matching the site's colors.
 */
export interface Photo {
  id: string
  alt: string
  credit: string
  creditUrl: string
  pageUrl: string
}

export const PHOTOS = {
  /** "Real signal, not vibes": decisions driven by measured data. */
  signal: {
    id: 'photo-1551288049-bebda4e38f71',
    alt: 'Performance analytics graphs on a laptop screen',
    credit: 'Luke Chesser',
    creditUrl: 'https://unsplash.com/@lukechesser',
    pageUrl: 'https://unsplash.com/photos/graphs-of-performance-analytics-on-a-laptop-screen-JKUTrJ4vK00',
  },
  /** "Learns which arm wins": choosing the strongest move from what's worked. */
  strategy: {
    id: 'photo-1758101308846-05b3bcba0473',
    alt: 'Chess pieces on a wooden board in warm light',
    credit: 'Nathan Bailly',
    creditUrl: 'https://unsplash.com/@nbailly',
    pageUrl: 'https://unsplash.com/photos/chess-pieces-arranged-on-a-wooden-board-BHNZkYdfPQM',
  },
  /** "You approve the risky parts": a person checking the work before it goes out. */
  review: {
    id: 'photo-1772588627373-729b0f47e5bb',
    alt: 'A person reviewing documents with a calculator and laptop',
    credit: 'Kelly Sikkema',
    creditUrl: 'https://unsplash.com/@kellysikkema',
    pageUrl: 'https://unsplash.com/photos/person-reviewing-documents-with-calculator-and-laptop-tLqtcDZltPs',
  },
  /** Login panel: someone getting to work on their campaign. */
  workspace: {
    id: 'photo-1762341118325-23fece6a2508',
    alt: 'A woman working on a laptop at a desk with a notebook beside her',
    credit: 'Zulfugar Karimov',
    creditUrl: 'https://unsplash.com/@zulfugarkarimov',
    pageUrl: 'https://unsplash.com/photos/woman-working-on-laptop-at-desk-with-notebook-on-desk-YHQfr1E2bJE',
  },
} satisfies Record<string, Photo>

/** Sized, cropped URL from Unsplash's image CDN. */
export const photoUrl = (p: Photo, width: number) => `https://images.unsplash.com/${p.id}?auto=format&fit=crop&w=${width}&q=70`
