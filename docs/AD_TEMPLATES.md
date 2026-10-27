# Product-first ad templates

Every ad is built around the campaign's **real product photo**. The photo is cut out with rembg (`src/tools/product_cutout.py`) and set into one of **34 layout templates** (`src/tools/ad_templates.py`). The image model never repaints the product. At most it paints a background with an empty spot, and only for the 8 templates marked 🎨. The other 26 draw their whole background in code, so they use no image quota and can't drift from the brand.

The templates come from a study of **128 real ads**:

| Area | Ads |
|---|---|
| Food & drink | 33 |
| Beauty, fashion & luxury | 31 |
| Tech, apps & services | 32 |
| Canva / Adobe Express / Envato / Freepik / Meta-style template systems | 32 |

The study also used 9 reference ads supplied by the product owner.

## How a template is chosen

1. The bandit (`src/tools/bandit.py`) picks the **image style × copy tone** arm as before. Its 20 arms and their learned data are unchanged.
2. Each image style is a **family** of templates. The creative prompt (`creative.generate` 2.0.0) lists the family's templates, each with a one-line "suits" note. The LLM picks the template that fits the product and situation, and fills its extra words (eyebrow, benefits, steps, stat, badge) **only from the idea**.
3. Fallbacks:
   - `resolve()` swaps an unknown template, or one from another family, for the family's first template.
   - It does the same for a template whose required words are missing (for example `big_number` with no number in the idea).
   - A failed background call leaves the template to draw its own.

**When the user picks one.** In the campaign composer (or Tools → Ad image), a person may choose a template, with a gallery of all 34 on a sample product to help them choose. A campaign's choice (`campaigns.ad_template`) holds for every round:
- **The style follows the template:** the bandit's arm is the best one in that template's family, and only the copy tone is learned. Variant B uses the second-best tone in that family.
- **Nothing swaps it:** a promoted A/B winner or a fatigue refresh of another style is moved into the family, and the template is drawn even if one of its extra words is missing.

## The 34 templates

| # | Template | Family (bandit style) | Inspired by | Suits |
|---|---|---|---|---|
| 1 | centered_hero | minimalist | Canva product post | any packaged product |
| 2 | icon_on_void | minimalist | Chanel No.5 (spotlight + reflection) | fragrance, watches, jewellery |
| 3 | podium_showcase | minimalist | Canva/Linearity podium posts | beauty, skincare, gadgets |
| 4 | giant_word_behind | minimalist | Nike Air Max, ORYGN, Canva "NEW PRODUCT" | sneakers, fashion, drinks |
| 5 | negative_space | minimalist | VW "Think Small" | premium, understated brands |
| 6 | type_manifesto | minimalist | The Ordinary, BMW "Company of Ideas" | ingredient-honest brands |
| 7 | inset_frame | minimalist | Envato framed editorial packs | artisan, boutique, home |
| 8 | scene_still_life 🎨 | lifestyle_aspirational | Aesop, Bose material scenes | premium beauty, home, food |
| 9 | lifestyle_inset 🎨 | lifestyle_aspirational | Nike / Meta lifestyle + product inset | apparel, fitness, travel |
| 10 | split_story | lifestyle_aspirational | Canva "New arrival" split | fashion, furniture |
| 11 | water_ripple 🎨 | lifestyle_aspirational | Evian, Adidas Liquid Billboard | drinks, water, skincare |
| 12 | flat_lay 🎨 | lifestyle_aspirational | Daniel Wellington flat lays | accessories, watches, snacks |
| 13 | oversized_world 🎨 | lifestyle_aspirational | Maybelline train, Jacquemus bags | launches, statement products |
| 14 | ingredient_halo 🎨 | lifestyle_aspirational | Mamaearth, juice-splash ads | natural foods, juices, skincare |
| 15 | dark_glow | lifestyle_aspirational | Pepsi 2023, Apple iPhone key visuals | tech, energy drinks, cola |
| 16 | feature_callouts | testimonial_social_proof | Spec-sheet ads (JBL, Bose), Foreplay callouts | gadgets, skincare |
| 17 | benefit_checklist | testimonial_social_proof | Cetaphil, CeraVe | health, personal care |
| 18 | numbered_steps | testimonial_social_proof | Nivea "3 easy steps" | routines, kits, recipes |
| 19 | big_number | testimonial_social_proof | Hawky data ads, Spotify Wrapped | a real number from the idea |
| 20 | tagline_quote | testimonial_social_proof | Review-card format (no fake reviewer) | brands with a strong tagline |
| 21 | us_vs_them | testimonial_social_proof | Pixel vs iPhone, Monzo before/after | products replacing a habit |
| 22 | phone_mockup | testimonial_social_proof | Duolingo, Creatopy app ads | apps, online stores, services |
| 23 | script_flank | humor_meme | "Sweet Drinks" orange juice reference | juices, sweets, desserts |
| 24 | doodle_pop | humor_meme | Lay's "Same Great Taste" reference | snacks, youth brands |
| 25 | blob_sticker | humor_meme | Freepik blob/sticker posts | D2C, kids, playful brands |
| 26 | paper_collage | humor_meme | Pinterest collage boards | handmade, craft, cafés |
| 27 | speech_bubble | humor_meme | Monzo coral, Duolingo notifications | apps, delivery, challengers |
| 28 | comic_scene 🎨 | humor_meme | Red Bull cartoons, Amul topicals | humour-led brands |
| 29 | starburst_badge | urgency_scarcity | Canva sale posts | offers, launches, new flavours |
| 30 | diagonal_flash | urgency_scarcity | Adobe Express flash sale | drops, flash offers |
| 31 | type_sandwich | urgency_scarcity | Dribbble type posters, "NEW PRODUCT" | product launches |
| 32 | rings_orbit | urgency_scarcity | Adobe Express launch rings | tech/product launches |
| 33 | corner_ribbon | urgency_scarcity | Cetaphil "NEW & IMPROVED" | new/improved products |
| 34 | event_title | urgency_scarcity | Stranger Things / event key visuals | events, pop-ups, workshops |

People appear only in templates 9 and 28. Every other template is product-only.

## Design rules applied by every template

These come from Meta and Google ad guidance and the template-library study.

- **Canvas and margins:** 1080 × 1080, with a 64 px safe margin for words and logo.
- **One hero:** the product, sharp and unobstructed, with a floor or drop shadow.
- **Type:**
  - at most two type families per ad (Anton, Montserrat, Fraunces, Pacifico, Caveat; all OFL);
  - headline at most 7 words, set large; nothing smaller than about 28 px;
  - text on photos sits on a scrim.
- **One call to action:** a verb-first pill in the bottom third. The logo is small, on a chip, in a corner or centred at the top or bottom.
- **At most one badge,** and it never invents an offer: it shows "NEW" unless the idea states the offer.
- **No invented claims.** Templates and the prompt never add any of these unless the idea states them:
  - customer names or quotes;
  - reviews or ratings;
  - statistics or prices;
  - discounts, deadlines or "limited" claims.
- **Brand kit:** the colour sets the palette (light, soft, dark and deep tints plus a contrasting accent), and the logo goes on every ad.
- **Repaints:** Gate 2's **New picture** keeps the template and words. Painted backgrounds are repainted; drawn ones move to their next colour or arrangement variant (`seed`).

## The research, by source

### Food & drink

- **Coca-Cola:** "Hands" (Cannes GP 2012), "Recycle Me" (GP 2024), Share a Coke, Taste the Feeling.
- **Other brands:** KFC "FCK" (Gold 2018), Pepsi Halloween cape and 2023 rebrand, Burger King Moldy Whopper and 2021 rebrand, Red Bull cartoons and cans-as-wings, Evian Live Young, Lay's Smiles.
- **McDonald's:** Wi-Fi fries, half-arches, Iconic Stacks, McDelivery pins, condensation.
- **Nestlé:** KitKat Pause, Breakmarks and Breakism; Nescafé red mug.
- **More brands:** Starbucks Unicorn Frappuccino, Tropicana orange-with-straw, Heinz "Pass the Heinz", "Draw Ketchup" and the tomato bottle, Chupa Chups ants, Oreo Daily Twist, Snickers "You're not you".
- **Indian brands:** Amul topicals, Zomato × Swiggy birthday, Swiggy "Why is this a Swiggy ad?".

### Beauty, fashion & luxury

- **Skincare:** The Ordinary (science outdoor ads and "Tricks"), Glossier "Skin first", Nivea Sun Kids, Clinique / Irving Penn, Aesop, Dove Real Beauty (two executions), L'Oréal Revitalift, Mamaearth, Kiehl's / CeraVe.
- **Makeup:** Maybelline CGI lashes, Gucci Beauty, Fenty 40 shades.
- **Fashion:** Jacquemus bags-on-wheels, Gucci illustrated still lifes, Zara wordmark posts.
- **Sportswear:** Nike Dream Crazy and Air Max, Adidas Liquid Billboard and Impossible Is Nothing, Puma Forever Faster, Converse portraits.
- **Luxury & accessories:** Cartier LOVE Unlimited, Tiffany box portal, Ray-Ban Never Hide, Rolex print, Omega Bond, Chanel No.5, Dior Sauvage, Daniel Wellington flat lays.

### Tech, apps & services

- **Apple:** Shot on iPhone (and Drawn on iPad), iPod silhouettes, AirPods Pro dancers, MacBook Air envelope, iPhone key visuals.
- **Cars:** VW Think Small and Lemon, Porsche Dream Ads and Vintage Meets Modern, BMW Company of Ideas.
- **Phones & audio:** Samsung S23 Tiny Type, Google Pixel Night Sight and contextual ads, JBL (Block Out The Chaos, Don't Lose Your Music, Still Life).
- **Apps & fintech:** Spotify Wrapped, Uber Eats bag-over, Tesco × Uber Eats, Monzo coral campaign and FT wrap, Duolingo Quitter's Day, Peloton, Revolut × Haaland.
- **Other:** IKEA "It's That Affordable" and "Cook This Page", Emirates Hello Tomorrow, StreetEasy, Gold's Gym, Netflix Narcos and Stranger Things.

### Template systems & guidance

- **Template libraries:**
  - Canva: product, podium, sale, new arrival, food, real estate and beauty templates.
  - Adobe Express: launch and flash-sale templates.
  - Envato: frame and gadget packs.
  - Freepik: blob/sale and fashion templates.
  - VistaCreate: grid and splash templates.
  - Creatopy: banner and phone templates.
  - Behance / Dribbble: floating and typographic posters.
  - Linearity: circle sale and starburst templates.
- **Ad-format libraries:** Pinterest collages, Foreplay / Trendtrack / Hawky ad formats (feature callout, us vs them, offer-led, colour line-up, material scene, review card, before & after, big number, seasonal).
- **Platform guidance:** Meta and Google display best practices (text ratio, safe zones, CTA, contrast, mobile legibility).
