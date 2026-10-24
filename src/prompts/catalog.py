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
        version="1.0.0",
        system="You are a marketing analyst writing terse, evidence-grounded feasibility rationales.",
        template=(
            "An ad campaign idea is:\n{idea}\n"
            "Research signals gathered:\n{signals}\n"
            "{similar}"
            "The computed feasibility score (0-100) is {score}.\n"
            "Write a 2-3 sentence rationale explaining what these signals suggest "
            "about this campaign's real-world momentum and feasibility. Write it in {language}."
        ),
    ),
    Prompt(
        id="audience.personas",
        version="1.2.0",  # 1.1.0: archetype (picks the persona's 3D figure); 1.2.0: gender (matches the figure)
        system=f"You are an audience research strategist. {_JSON_ONLY}",
        template=(
            "Ad campaign idea:\n{idea}\n"
            "Feasibility rationale:\n{rationale}\n\n"
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
        version="1.3.0",  # 1.1.0: brand kit section; 1.2.0: playbook section; 1.3.0: headline, CTA, ad-style visual
        system=f"You are an ad creative director. {_JSON_ONLY}",
        template=(
            "Ad campaign idea:\n{idea}\n"
            "Target persona:\n{persona}\n"
            "{brand}"
            "{playbook}"
            "Required image style archetype: {image_style}\n"
            "Required copy tone archetype: {copy_tone}\n"
            "{directive}{safety}\n"
            "Write ad creative for this persona, executed within the required style/tone archetypes above "
            "(don't invent a different style). Never include links, email addresses or phone numbers in the "
            "copy (the call-to-action link is added separately). Respond with ONLY a JSON object, no prose, "
            'with exactly four keys: "copy" (a short ad copy, 2-3 sentences, written in '
            "{language} since that is this campaign's target-audience language), "
            "\"headline\" (the ad's on-image headline in {language}: at most 8 words, one concrete benefit, "
            'no hashtags, emoji or quotes), "cta" (a 2-4 word call-to-action button label in {language}, '
            "e.g. \"Book a table\") and \"image_prompt\" (the ad's visual for an image generation model, always "
            "written in English regardless of the copy's language, since image generation models are "
            "English-prompt-optimized: a professional advertising photograph of the product or service in "
            "use by someone like the persona, one clear focal subject, clean uncluttered background, "
            "commercial lighting, and the bottom third of the frame kept simple and calm because the headline "
            "is set there later; never ask for any text, letters, signs, logos or watermarks in the image)."
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
]

PROMPTS: dict[str, Prompt] = {p.id: p for p in _CATALOG}
