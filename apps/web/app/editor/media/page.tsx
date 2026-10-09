import Link from "next/link"

import { MediaLibrary } from "@/components/editor/media-library"

export default function MediaPage() {
  return (
    <div className="space-y-4">
      <Link href="/editor" className="text-xs text-white/50 hover:text-white/80">
        ← All articles
      </Link>
      <h1 className="text-xl font-bold text-white">Media library</h1>
      <MediaLibrary mode="manage" />
    </div>
  )
}
