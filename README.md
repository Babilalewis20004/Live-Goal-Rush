# LivePitch

A live football scores dashboard built with Next.js — Champions League, Premier League, LaLiga, Serie A, Bundesliga and Ligue 1 matches grouped by competition, with a highlights carousel and per-match event/stats detail. All match data in this project is static mock data (see [lib/matches.ts](lib/matches.ts)) for demo purposes; there is no live data source wired up.

## Requirements

- Node.js 20+ (Node 24 has also been verified)
- npm (ships with Node.js)

## Setup

```bash
npm install
npm run dev
```

Then open [http://localhost:3000](http://localhost:3000).

## Scripts

| Command         | Description                              |
| --------------- | ----------------------------------------- |
| `npm run dev`   | Start the dev server with hot reload      |
| `npm run build` | Create a production build                 |
| `npm start`     | Run the production build (run after `build`) |

## Project structure

```
app/                  Next.js App Router entry (layout, page, global styles)
components/           UI components (board, league/match cards, carousel, badges)
components/ui/        Shared primitives (shadcn-style button)
lib/matches.ts        Mock league/match data + shared types
public/               Static assets (icons, placeholders)
```

## Notes

- `next.config.mjs` sets `typescript.ignoreBuildErrors: true`, so `npm run build` will succeed even if there are type errors. Run `npx tsc --noEmit` if you want a strict type check.
- Analytics (`@vercel/analytics`) only loads in production builds.
