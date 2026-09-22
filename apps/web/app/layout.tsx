import { Analytics } from '@vercel/analytics/next'
import type { Metadata, Viewport } from 'next'
import './globals.css'
import { AuthProvider } from '@/lib/auth-context'
import { NavBar } from '@/components/nav-bar'
import { ServiceWorkerRegister } from '@/components/service-worker-register'
import { getServerUser } from '@/lib/server-auth'

export const metadata: Metadata = {
  title: 'LivePitch · Live Football Scores',
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
        {process.env.NODE_ENV === 'production' && <Analytics />}
      </body>
    </html>
  )
}
