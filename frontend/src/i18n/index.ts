import i18next from 'i18next'
import { initReactI18next } from 'react-i18next'
import en from './locales/en.json'
import es from './locales/es.json'
import fr from './locales/fr.json'
import hi from './locales/hi.json'
import pt from './locales/pt.json'

export const UI_LOCALES = [
  { code: 'en', label: 'English' },
  { code: 'es', label: 'Español' },
  { code: 'fr', label: 'Français' },
  { code: 'hi', label: 'हिन्दी' },
  { code: 'pt', label: 'Português' },
] as const

const STORAGE_KEY = 'marketingos_ui_locale'

i18next.use(initReactI18next).init({
  resources: { en: { translation: en }, es: { translation: es }, fr: { translation: fr }, hi: { translation: hi }, pt: { translation: pt } },
  lng: localStorage.getItem(STORAGE_KEY) ?? 'en',
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
})

i18next.on('languageChanged', (lng) => {
  localStorage.setItem(STORAGE_KEY, lng)
})

export default i18next
