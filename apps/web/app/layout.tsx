import { Analytics } from '@vercel/analytics/next'
import type { Metadata, Viewport } from 'next'
import './globals.css'
import { AuthProvider } from '@/lib/auth-context'
import { NavBar } from '@/components/nav-bar'
import { ServiceWorkerRegister } from '@/components/service-worker-register'
import { SITE_NAME, SITE_URL } from '@/lib/seo'
import { getServerUser } from '@/lib/server-auth'

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: 'LivePitch · Live Football Scores', template: `%s · ${SITE_NAME}` },
  openGraph: { siteName: SITE_NAME, type: 'website', locale: 'en_GB' },
  description: 'Real-time livescores for major football leagues — Champions League, Premier League, LaLiga, Serie A, Bundesliga and Ligue 1.',
  generator: 'v0.app',
  manifest: '/manifest.json',
  icons: {
    icon: [
      {
        url: '/icon-light-32x32.png',
        media: '(prefers-color-scheme: light)',
      },
      {
        url: '/icon-dark-32x32.png',
        media: '(prefers-color-scheme: dark)',
      },
      {
        url: '/icon.svg',
        type: 'image/svg+xml',
      },
    ],
    apple: '/apple-icon.png',
  },
}

export const viewport: Viewport = {
  colorScheme: 'dark',
  themeColor: '#070b09',
}

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  const initialUser = await getServerUser()

  return (
    <html lang="en">
      <body className="antialiased bg-[#070b09] text-white">
        <AuthProvider initialUser={initialUser}>
          <ServiceWorkerRegister />
          <NavBar />
          {children}
        </AuthProvider>
        {/* Vercel Analytics serves its script from /_vercel/insights, which exists only on Vercel: elsewhere it is a 404 on every page */}
        {process.env.NODE_ENV === 'production' && process.env.VERCEL && <Analytics />}
      </body>
    </html>
  )
}
