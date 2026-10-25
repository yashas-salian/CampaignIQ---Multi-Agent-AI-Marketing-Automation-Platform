// The ad templates (src/tools/ad_templates.py), by bandit image style.
// Kept in step with the backend by tests/unit/test_ad_templates.py.
export const AD_TEMPLATE_FAMILIES: Record<string, string[]> = {
  minimalist: ['centered_hero', 'icon_on_void', 'podium_showcase', 'giant_word_behind', 'negative_space', 'type_manifesto', 'inset_frame'],
  lifestyle_aspirational: ['scene_still_life', 'lifestyle_inset', 'split_story', 'water_ripple', 'flat_lay', 'oversized_world', 'ingredient_halo', 'dark_glow'],
  testimonial_social_proof: ['feature_callouts', 'benefit_checklist', 'numbered_steps', 'big_number', 'tagline_quote', 'us_vs_them', 'phone_mockup'],
  humor_meme: ['script_flank', 'doodle_pop', 'blob_sticker', 'paper_collage', 'speech_bubble', 'comic_scene'],
  urgency_scarcity: ['starburst_badge', 'diagonal_flash', 'type_sandwich', 'rings_orbit', 'corner_ribbon', 'event_title'],
}

export const AD_TEMPLATES: string[] = Object.values(AD_TEMPLATE_FAMILIES).flat()
