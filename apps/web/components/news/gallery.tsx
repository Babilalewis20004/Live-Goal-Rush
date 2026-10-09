import Image from "next/image"

import type { GalleryImage } from "@/types/api"

/** An article's photo gallery: thumbnails that open the large rendition in a new tab.
 * Every image has alt text (its caption, else the editor's description, else the file name). */
export function Gallery({ images }: { images: GalleryImage[] }) {
  if (images.length === 0) return null
  return (
    <section aria-labelledby="gallery-heading" className="mt-8">
      <h2 id="gallery-heading" className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/40">
        Gallery
      </h2>
      <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {images.map((image) => (
          <li key={image.media_id}>
            <figure>
              <a
                href={image.url}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={`${image.alt} (opens the full-size image)`}
                className="relative block aspect-[4/3] overflow-hidden rounded-xl bg-white/[0.04] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-400"
              >
                <Image src={image.thumb_url} alt={image.alt} fill sizes="(min-width: 640px) 220px, 50vw" className="object-cover" loading="lazy" unoptimized />
              </a>
              {image.caption && <figcaption className="mt-1 text-[11px] text-white/50">{image.caption}</figcaption>}
            </figure>
          </li>
        ))}
      </ul>
    </section>
  )
}
