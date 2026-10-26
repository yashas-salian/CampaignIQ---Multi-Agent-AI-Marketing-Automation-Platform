import css from './PageLoader.module.css'

/**
 * The CampaignIQ robot, redrawn as vector so each part can move: the growth
 * swoosh draws itself round, the chart bars rise in turn, the megaphone sends
 * out sound, and the robot bobs and blinks. Decorative (the loader's caption
 * carries the meaning).
 */
export default function LoaderMascot() {
  return (
    <svg className={css.mascot} viewBox="0 0 220 226" aria-hidden="true">
      <defs>
        <linearGradient id="mos-orange" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ff9a2e" />
          <stop offset="1" stopColor="#e8431b" />
        </linearGradient>
        <radialGradient id="mos-glow">
          <stop offset="0" stopColor="#ff7a2a" stopOpacity="0.35" />
          <stop offset="1" stopColor="#ff7a2a" stopOpacity="0" />
        </radialGradient>
      </defs>

      <circle cx="110" cy="112" r="100" fill="url(#mos-glow)" className={css.glow} />

      {/* Growth swoosh: the back half sits behind the robot. */}
      <path className={css.swooshBack} d="M186 134 C 176 104, 64 100, 32 134" fill="none" stroke="url(#mos-orange)" strokeWidth="9" strokeLinecap="round" />

      <g className={css.robot}>
        {/* Body with the rising bar chart */}
        <path d="M66 176 C 66 140, 86 124, 112 124 C 140 124, 158 142, 158 176 Z" fill="#141518" />
        <rect className={`${css.bar} ${css.bar1}`} x="96" y="150" width="14" height="22" rx="3" fill="url(#mos-orange)" />
        <rect className={`${css.bar} ${css.bar2}`} x="114" y="141" width="14" height="31" rx="3" fill="url(#mos-orange)" />
        <rect className={`${css.bar} ${css.bar3}`} x="132" y="131" width="14" height="41" rx="3" fill="url(#mos-orange)" />

        <g className={css.head}>
          {/* Megaphone + sound */}
          <path d="M138 70 L 176 44 L 186 86 Z" fill="url(#mos-orange)" />
          <path d="M176 44 L 186 86" stroke="#141518" strokeWidth="5" strokeLinecap="round" />
          <g stroke="url(#mos-orange)" strokeWidth="6" strokeLinecap="round" fill="none">
            <path className={`${css.wave} ${css.wave1}`} d="M190 40 L 200 28" />
            <path className={`${css.wave} ${css.wave2}`} d="M196 62 L 210 58" />
            <path className={`${css.wave} ${css.wave3}`} d="M194 84 L 208 90" />
          </g>

          {/* Head, ear cups, visor and smiling eyes */}
          <ellipse cx="104" cy="92" rx="56" ry="46" transform="rotate(-8 104 92)" fill="url(#mos-orange)" />
          <circle cx="48" cy="106" r="15" fill="url(#mos-orange)" stroke="#141518" strokeWidth="4" />
          <circle cx="156" cy="84" r="9" fill="url(#mos-orange)" stroke="#141518" strokeWidth="4" />
          <rect x="66" y="66" width="80" height="50" rx="24" transform="rotate(-8 106 91)" fill="#141518" />
          <g className={css.eyes} stroke="url(#mos-orange)" strokeWidth="6" strokeLinecap="round" fill="none">
            <path d="M84 96 Q 92 84 100 94" />
            <path d="M114 92 Q 122 80 130 90" />
          </g>
        </g>
      </g>

      {/* Front half of the swoosh, ending in the arrowhead */}
      <path className={css.swoosh} d="M32 134 C 10 172, 62 216, 134 208 C 176 203, 196 174, 186 142" fill="none" stroke="url(#mos-orange)" strokeWidth="9" strokeLinecap="round" />
      <path className={css.arrow} d="M172 146 L 186 120 L 200 146 Z" fill="url(#mos-orange)" />
    </svg>
  )
}
