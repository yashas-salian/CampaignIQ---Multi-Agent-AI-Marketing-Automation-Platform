"""Every production prompt. Change the text -> bump the version (patch for
wording, minor for new instructions, major for a new output format) and run
`python -m src.prompts --update-fingerprints`."""
from src.prompts import Prompt

_JSON_ONLY = "You output only valid JSON, never prose or markdown fences."

_CATALOG = [
    Prompt(
        id="idea_intake.classify",
        version="1.0.0",
        system=f"You are a strict classifier. {_JSON_ONLY}",
        template=(
            "Campaign idea:\n{idea}\n\n"
            "Classify this idea into exactly one of these domain/category tags: {categories}. "
            'Respond with ONLY a JSON object, no prose, with exactly one key: "domain_category".'
        ),
    ),
    Prompt(
        id="feasibility.keywords",
        version="1.0.0",
        system=f"You are a precise translator and keyword extractor. {_JSON_ONLY}",
        template=(
            "Campaign idea:\n{idea}\n\n"
            "Extract a short 2-4 word search keyword phrase capturing the core product/topic — suitable "
            "as a Google Trends / news search query, not a full sentence. Respond with ONLY a JSON object, "
            'no prose, with exactly two keys: "keywords_en" (the phrase in English) and "keywords_localized" '
            "(the same phrase translated into {language})."
        ),
    ),
    Prompt(
        id="feasibility.rationale",
        version="1.1.0",  # 1.1.0: brand memory section (background only; the score is computed, not written)
        system="You are a marketing analyst writing terse, evidence-grounded feasibility rationales.",
        template=(
            "An ad campaign idea is:\n{idea}\n"
            "Research signals gathered:\n{signals}\n"
            "{similar}"
            "{memory}"
            "The computed feasibility score (0-100) is {score}.\n"
            "Write a 2-3 sentence rationale explaining what these signals suggest "
            "about this campaign's real-world momentum and feasibility. Write it in {language}."
        ),
    ),
    Prompt(
        id="audience.personas",
        version="1.3.0",  # 1.1.0: archetype (picks the persona's 3D figure); 1.2.0: gender (matches the figure); 1.3.0: brand memory
        system=f"You are an audience research strategist. {_JSON_ONLY}",
        template=(
            "Ad campaign idea:\n{idea}\n"
            "Feasibility rationale:\n{rationale}\n\n"
            "{memory}"
            "Generate exactly {n} distinct ideal-customer-profile personas for this campaign. "
            "Respond with ONLY a JSON array, no prose, where each element has exactly these keys: "
            '"name", "demographics", "psychographics", "channel_fit", "messaging_angle" (each a single '
            "plain string value, never a nested object or list, written in "
            "{language} since these personas represent that target market), plus "
            '"age_bracket" (exactly one of {age_brackets}, always in English -- this is a fixed '
            'category label, not display text), "income_tier" (exactly one of {income_tiers}, same), '
            '"archetype" (the one of {archetypes} that best describes who this person is, by occupation or life '
            'stage; "general" if none fits; always in English) and "gender" (exactly one of {genders}, the '
            "persona's gender, consistent with their name and description; always in English)."
        ),
    ),
    Prompt(
        id="creative.generate",
        # 1.1.0: brand kit section; 1.2.0: playbook section; 1.3.0: headline, CTA, ad-style visual;
        # 2.0.0: product-first templates (src/tools/ad_templates.py), tagline, no invented claims; 2.1.0: brand memory
        version="2.1.0",
        system=f"You are an ad creative director. {_JSON_ONLY}",
        template=(
            "Ad campaign idea:\n{idea}\n"
            "{tagline}"
            "Target persona:\n{persona}\n"
            "{brand}"
            "{playbook}"
            "{memory}"
            "Required image style archetype: {image_style}\n"
            "Required copy tone archetype: {copy_tone}\n"
            "{directive}{safety}\n"
            "Write ad creative for this persona, executed within the required style/tone archetypes above "
            "(don't invent a different style). The PRODUCT is the hero of the ad, not a person or the "
            "surroundings. Never include links, email addresses or phone numbers in the copy (the "
            "call-to-action link is added separately). Never invent anything the idea doesn't state: no "
            "customer names, quotes or testimonials, no reviews or ratings, no statistics or numbers, no "
            "discounts, prices or deadlines, no 'limited stock' or 'spots running out'. Urgency or proof "
            "tones work with what the idea really says. "
            "{visual}"
            "Respond with ONLY a JSON object, no prose, with exactly these keys: "
            '"copy" (a short ad copy, 2-3 sentences, written in {language} since that is this campaign\'s '
            "target-audience language; it may echo the tagline), "
            "\"headline\" (the ad's on-image headline in {language}: at most 7 words, one concrete benefit, "
            'no hashtags, emoji or quotes), "cta" (a 2-4 word call-to-action button label in {language}, '
            'e.g. "Book a table"), '
            "{keys}"
        ),
    ),
    Prompt(
        id="preflight.panel",
        version="1.0.0",
        system=(
            "You are a panel of skeptical target-audience consumers giving honest, critical ad "
            f"feedback. {_JSON_ONLY}"
        ),
        template=(
            "Ad copy:\n{copy}\n"
            "Image description:\n{image_prompt}\n\n"
            "You are simulating how this panel of target personas would honestly react:\n{panel}\n\n"
            "Estimate an overall predicted engagement score (0-100, where 100 = extremely likely to "
            "engage/click/share, 0 = would ignore or dislike it). Respond with ONLY a JSON object, no "
            'prose, with exactly two keys: "predicted_engagement" (integer 0-100) and "panel_feedback" '
            "(one or two sentences summarizing the panel's honest reaction, written in {language})."
        ),
    ),
    Prompt(
        id="focus_group.react",
        version="1.0.0",
        system=(
            "You simulate a small focus group of real people seeing an ad in their feed. Each person reacts "
            f"honestly in their own voice, including indifference or objections. {_JSON_ONLY}"
        ),
        template=(
            "Ad copy:\n{copy}\n"
            "Image description:\n{image_prompt}\n\n"
            "The focus group, one person per line:\n{panel}\n\n"
            "For each person, in the same order, give their honest first reaction. Respond with ONLY a JSON "
            'array with one object per person, each with exactly these keys: "name" (as given), "reaction" '
            '(exactly one of "click", "scroll", "object", always in English: would click, would scroll past, '
            'or would actively object), "likelihood" (integer 0-100, how likely they are to click) and "quote" '
            "(one first-person sentence under 25 words, in {language}, saying why)."
        ),
    ),
    Prompt(
        id="playbook.write",
        version="1.0.0",
        system=f"You are a senior performance marketer writing a short, practical playbook from real campaign results. {_JSON_ONLY}",
        template=(
            "Industry: {domain}\n"
            "Measured results from this organisation's campaigns in this industry (reward 0-1, higher is better; "
            "n = measured rounds):\n{stats}\n\n"
            "Best-performing ad copy:\n{best}\n\n"
            "Weakest ad copy:\n{worst}\n\n"
            "Notes from the campaigns (round reviews and audience reactions):\n{notes}\n\n"
            "Write a playbook a marketer can act on next time, grounded only in these results (say so when "
            "evidence is thin, e.g. based on 2 rounds). Respond with ONLY a JSON object with exactly these keys: "
            '"headline" (one sentence, the single most useful lesson), "do" (2-4 short concrete recommendations), '
            '"avoid" (1-3 things that underperformed), "audience" (1-3 notes on who responded and why) and '
            '"next_test" (one sentence: the most valuable thing to test next). Every string in {language}.'
        ),
    ),
    Prompt(
        id="feedback.decide",
        version="1.0.0",
        system=f"You are a marketing performance analyst deciding whether a campaign is working. {_JSON_ONLY}",
        template=(
            "Ad campaign idea:\n{idea}\n"
            "Round {round} results: overall_reward={reward} (0-1 scale), "
            "per-channel rewards: {channel_rewards}\n"
            "Stakeholder feedback:\n{comment}\n\n"
            "Decide whether this campaign should continue to another round, and if so, what should "
            "be adjusted (tone, image style, channel emphasis, etc.) for the next round's creative. "
            "Respond with ONLY a JSON object, no prose, with exactly three keys: "
            '"continue_campaign" (boolean), "reasoning" (one sentence), "adjustments" (a short '
            "directive to feed into the next round's creative generation, empty string if not continuing). "
            'Write "reasoning" and "adjustments" in {language}.'
        ),
    ),
    Prompt(
        id="eval.judge_personas",
        version="1.0.0",
        guard=False,  # offline eval over the curated golden set
        system=f"You are a strict, consistent marketing quality judge. {_JSON_ONLY}",
        template=(
            'Campaign idea: "{idea}"\n\nGenerated personas:\n{personas}\n\n'
            "Judge these personas on relevance to the idea, specificity (not generic), and actionability "
            "for an ad campaign. Respond with ONLY a JSON object, no prose, with exactly two keys: "
            '"score" (integer 1-5, 5=excellent) and "reasoning" (one sentence).'
        ),
    ),
    Prompt(
        id="crashtest.simulate",
        version="1.0.0",
        system=(
            "You stress-test ads before launch by role-playing specific people in specific situations. You look for "
            "real ways the ad could fail, and you say so plainly when it holds up. You never invent problems to fill "
            f"a quota. {_JSON_ONLY}"
        ),
        template=(
            "What the brand is advertising:\n{idea}\n"
            "The ad:\n{ad}\n"
            "The intended audience:\n{personas}\n\n"
            "Play each of these scenarios in turn:\n{scenarios}\n\n"
            "For each scenario, decide whether the ad holds up for that person. Respond with ONLY a JSON object with one "
            'key "scenarios": an array with one object per scenario, each with "id" (as given), "verdict" ("pass", '
            '"concern" or "fail") and "findings" (an array of 0-2 objects; empty when it passes). Each finding has: '
            '"type" (exactly one of: {types}), "severity" ("low", "medium" or "high"), "quote" (the exact words from the '
            'ad that cause it, copied character for character, or "" if it is about the ad as a whole), "problem" (one '
            'sentence: what goes wrong for this person) and "fix" (one sentence: a concrete change). Write "problem" and '
            '"fix" in {language}. Only report what this person would really notice; do not repeat the same problem in '
            "several scenarios."
        ),
    ),
    Prompt(
        id="crashtest.revise",
        version="1.1.0",  # 1.1.0: no new product facts, never longer than the original
        system=f"You are a careful ad copy editor who fixes problems without adding new claims. {_JSON_ONLY}",
        template=(
            "What the brand is advertising (the only facts you may use):\n{idea}\n"
            "The brand's tagline:\n{tagline}\n"
            "The current ad:\n{ad}\n"
            "Problems found by a pre-launch crash test:\n{issues}\n\n"
            "Rewrite the ad so it fixes every problem above while keeping what works. Never add anything the brand "
            "didn't state: no customer names, quotes, reviews or ratings, no numbers, prices, percentages, deadlines, "
            "scarcity or popularity claims, no questions about the reader's health, money or personal life, and no new "
            "facts about the product (locations, availability, timing, data, fees, features). When a problem could only "
            "be fixed with information the brand didn't give, remove or soften the claim instead of adding anything. "
            "The result must be no longer than the current ad. Keep the same language ({language}). "
            'Respond with ONLY a JSON object with exactly these keys: "copy" (the post text, 2-3 sentences), "headline" '
            '(on-image headline, at most 7 words, no hashtags or emoji), "cta" (a 2-4 word button label) and "changes" '
            "(an array of short strings, one per change you made and why)."
        ),
    ),
    Prompt(
        id="email.audience",
        version="1.0.0",
        system=(
            "You are an email marketer choosing which of a brand's own subscribers should get a campaign. You only use "
            f"the groups listed; you never invent tags, products or places. {_JSON_ONLY}"
        ),
        template=(
            "The campaign:\n{idea}\n"
            "Who it is for (the campaign's personas):\n{personas}\n"
            "The brand's subscribers, as groups with how many people are in each (the only names you may use):\n{catalog}\n\n"
            "Pick the subscribers this campaign fits best. Prefer a focused group over everyone, but don't narrow it to a "
            "handful of people. Respond with ONLY a JSON object with exactly two keys: \"filter\" (an object using only "
            "these optional keys: \"tags_any\" and \"tags_none\" (lists of tag names from above), \"purchased_within_days\" "
            "or \"not_purchased_within_days\" (a number of days), \"product_any\" (product names from above), "
            "\"country_any\" (country names from above)) and \"reason\" (one sentence in {language} saying why this group)."
        ),
    ),
    Prompt(
        id="competitor.explain",
        version="1.0.0",
        system=(
            "You are a cautious market analyst. You separate what was observed from what it might mean, you offer "
            "competing explanations rather than one confident story, and you never invent facts about a company. "
            f"{_JSON_ONLY}"
        ),
        template=(
            "A competitor we track:\n{competitor}\n"
            "What was observed (the only facts you may use):\n{evidence}\n\n"
            "Why might they have done this? Give 2 or 3 different, plausible explanations: they are hypotheses, not "
            "facts. Do not recommend what we should do and do not suggest copying their wording. Respond with ONLY a "
            'JSON object with one key "hypotheses": an array of objects, each with "hypothesis" (one sentence), '
            '"would_confirm" (one sentence: what later evidence would support it) and "would_refute" (one sentence: '
            "what would rule it out). Write in {language}."
        ),
    ),
]

PROMPTS: dict[str, Prompt] = {p.id: p for p in _CATALOG}
