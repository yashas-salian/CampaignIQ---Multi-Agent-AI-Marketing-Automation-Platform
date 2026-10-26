// Must match DomainCategory in src/capabilities/idea_intake.py (and the domain_corrections check in supabase/migrations).
export const DOMAINS = [
  'fitness_wellness', 'b2b_saas', 'ecommerce_retail', 'food_beverage', 'finance_fintech', 'education',
  'consumer_electronics', 'travel_hospitality', 'real_estate', 'healthcare', 'entertainment_media', 'other',
] as const
