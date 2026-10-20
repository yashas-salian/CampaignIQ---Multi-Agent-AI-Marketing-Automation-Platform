import { useState } from 'react'
import { type Photo as PhotoData, photoUrl } from '../lib/photos'
import styles from './Photo.module.css'

/** A credited Unsplash photo that fades in once loaded, cropped to fill its box. */
export default function Photo({ photo, className = '', sizes = '(max-width: 860px) 100vw, 560px' }: { photo: PhotoData; className?: string; sizes?: string }) {
  const [loaded, setLoaded] = useState(false)
  return (
    <figure className={`${styles.photo} ${loaded ? styles.loaded : ''} ${className}`}>
      <img
        src={photoUrl(photo, 1200)}
        srcSet={`${photoUrl(photo, 600)} 600w, ${photoUrl(photo, 1200)} 1200w, ${photoUrl(photo, 1800)} 1800w`}
        sizes={sizes}
        alt={photo.alt}
        loading="lazy"
        decoding="async"
        onLoad={() => setLoaded(true)}
      />
      <figcaption>
        Photo:{' '}
        <a href={photo.creditUrl} target="_blank" rel="noopener noreferrer">
          {photo.credit}
        </a>{' '}
        /{' '}
        <a href={photo.pageUrl} target="_blank" rel="noopener noreferrer">
          Unsplash
        </a>
      </figcaption>
    </figure>
  )
}
