/**
 * The MarketingOS emblem (public/brand/, cropped from the source artwork in
 * public/media/). Its black background is part of the mark, so it's shown as
 * a rounded app-icon tile. Decorative here: the "MarketingOS" text beside it
 * carries the name, so alt is empty.
 */
export default function LogoMark({ className = '', size = 'small' }: { className?: string; size?: 'small' | 'large' }) {
  const src = size === 'large' ? '/brand/logo-1024.webp' : '/brand/logo-256.webp'
  const px = size === 'large' ? 1024 : 256
  return <img src={src} width={px} height={px} alt="" aria-hidden="true" decoding="async" className={className} />
}
