export type MatchStatus = "live" | "finished" | "upcoming" | "halftime"

export type Team = {
  name: string
  short: string
  color: string
  /** secondary crest color */
  accent: string
}

export type MatchEventType = "goal" | "own-goal" | "penalty" | "yellow" | "red" | "sub"

export type MatchEvent = {
  minute: number
  type: MatchEventType
  team: "home" | "away"
  player: string
  /** assist provider, penalty note, or player coming off in a sub */
  detail?: string
}

export type TeamStat = {
  label: string
  /** raw values; bars are drawn proportionally */
  home: number
  away: number
  /** render values with a percent sign */
  percent?: boolean
}

export type Match = {
  id: string
  status: MatchStatus
  /** live minute, e.g. 67 */
  minute?: number
  /** kickoff time for upcoming matches, e.g. "20:45" */
  kickoff?: string
  /** day offset relative to today: -1 yesterday, 0 today, 1 tomorrow */
  day: number
  home: Team
  away: Team
  homeScore: number
  awayScore: number
  /** aggregate note for knockout ties, optional */
  note?: string
  venue?: string
  events?: MatchEvent[]
  stats?: TeamStat[]
}

export type League = {
  id: string
  name: string
  country: string
  color: string
  matches: Match[]
}

const t = (name: string, short: string, color: string, accent: string): Team => ({
  name,
  short,
  color,
  accent,
})

export const leagues: League[] = [
  {
    id: "ucl",
    name: "Champions League",
    country: "Europe",
    color: "#1e40af",
    matches: [
      {
        id: "ucl-1",
        status: "live",
        minute: 74,
        day: 0,
        home: t("Real Madrid", "RMA", "#facc15", "#1e3a8a"),
        away: t("Man City", "MCI", "#60a5fa", "#0c4a6e"),
        homeScore: 2,
        awayScore: 2,
        note: "Quarter-final · 2nd leg",
        venue: "Santiago Bernabéu",
        events: [
          { minute: 12, type: "goal", team: "home", player: "Vinícius Jr.", detail: "Bellingham" },
          { minute: 23, type: "goal", team: "away", player: "Haaland", detail: "De Bruyne" },
          { minute: 34, type: "yellow", team: "away", player: "Rodri" },
          { minute: 51, type: "penalty", team: "home", player: "Mbappé", detail: "Penalty" },
          { minute: 66, type: "goal", team: "away", player: "Foden", detail: "Grealish" },
          { minute: 70, type: "sub", team: "home", player: "Rodrygo", detail: "Vinícius Jr." },
        ],
        stats: [
          { label: "Possession", home: 52, away: 48, percent: true },
          { label: "Shots", home: 11, away: 13 },
          { label: "Shots on target", home: 5, away: 6 },
          { label: "Corners", home: 4, away: 7 },
          { label: "Fouls", home: 9, away: 12 },
        ],
      },
      {
        id: "ucl-2",
        status: "live",
        minute: 58,
        day: 0,
        home: t("Bayern München", "BAY", "#ef4444", "#7f1d1d"),
        away: t("Inter", "INT", "#38bdf8", "#0f172a"),
        homeScore: 1,
        awayScore: 0,
        note: "Quarter-final · 2nd leg",
        venue: "Allianz Arena",
        events: [
          { minute: 28, type: "goal", team: "home", player: "Kane", detail: "Musiala" },
          { minute: 41, type: "yellow", team: "away", player: "Barella" },
        ],
        stats: [
          { label: "Possession", home: 61, away: 39, percent: true },
          { label: "Shots", home: 14, away: 6 },
          { label: "Shots on target", home: 6, away: 2 },
          { label: "Corners", home: 8, away: 3 },
          { label: "Fouls", home: 7, away: 11 },
        ],
      },
      {
        id: "ucl-3",
        status: "upcoming",
        kickoff: "21:00",
        day: 0,
        home: t("Arsenal", "ARS", "#f87171", "#7f1d1d"),
        away: t("PSG", "PSG", "#1d4ed8", "#ef4444"),
        homeScore: 0,
        awayScore: 0,
        note: "Semi-final · 1st leg",
        venue: "Emirates Stadium",
      },
    ],
  },
  {
    id: "epl",
    name: "Premier League",
    country: "England",
    color: "#7c3aed",
    matches: [
      {
        id: "epl-1",
        status: "live",
        minute: 63,
        day: 0,
        home: t("Liverpool", "LIV", "#ef4444", "#7f1d1d"),
        away: t("Chelsea", "CHE", "#3b82f6", "#1e3a8a"),
        homeScore: 3,
        awayScore: 1,
        venue: "Anfield",
        events: [
          { minute: 8, type: "goal", team: "home", player: "Salah", detail: "Szoboszlai" },
          { minute: 19, type: "goal", team: "away", player: "Palmer", detail: "Penalty" },
          { minute: 37, type: "goal", team: "home", player: "Núñez", detail: "Salah" },
          { minute: 45, type: "yellow", team: "away", player: "Caicedo" },
          { minute: 58, type: "goal", team: "home", player: "Gakpo", detail: "Robertson" },
        ],
        stats: [
          { label: "Possession", home: 57, away: 43, percent: true },
          { label: "Shots", home: 16, away: 8 },
          { label: "Shots on target", home: 8, away: 3 },
          { label: "Corners", home: 6, away: 4 },
          { label: "Fouls", home: 6, away: 10 },
        ],
      },
      {
        id: "epl-2",
        status: "halftime",
        minute: 45,
        day: 0,
        home: t("Tottenham", "TOT", "#e2e8f0", "#1e293b"),
        away: t("Newcastle", "NEW", "#94a3b8", "#0f172a"),
        homeScore: 0,
        awayScore: 0,
        venue: "Tottenham Hotspur Stadium",
        events: [{ minute: 31, type: "yellow", team: "home", player: "Bentancur" }],
        stats: [
          { label: "Possession", home: 49, away: 51, percent: true },
          { label: "Shots", home: 5, away: 4 },
          { label: "Shots on target", home: 1, away: 2 },
          { label: "Corners", home: 2, away: 3 },
          { label: "Fouls", home: 5, away: 4 },
        ],
      },
      {
        id: "epl-3",
        status: "finished",
        day: -1,
        home: t("Man United", "MUN", "#dc2626", "#facc15"),
        away: t("Aston Villa", "AVL", "#7dd3fc", "#4c1d95"),
        homeScore: 2,
        awayScore: 2,
        venue: "Old Trafford",
        events: [
          { minute: 14, type: "goal", team: "away", player: "Watkins", detail: "Bailey" },
          { minute: 30, type: "goal", team: "home", player: "Fernandes", detail: "Penalty" },
          { minute: 62, type: "goal", team: "home", player: "Højlund", detail: "Garnacho" },
          { minute: 78, type: "red", team: "home", player: "Casemiro" },
          { minute: 88, type: "goal", team: "away", player: "Rogers", detail: "Tielemans" },
        ],
        stats: [
          { label: "Possession", home: 45, away: 55, percent: true },
          { label: "Shots", home: 10, away: 15 },
          { label: "Shots on target", home: 4, away: 6 },
          { label: "Corners", home: 3, away: 8 },
          { label: "Fouls", home: 13, away: 9 },
        ],
      },
      {
        id: "epl-4",
        status: "upcoming",
        kickoff: "18:30",
        day: 1,
        home: t("Brighton", "BHA", "#38bdf8", "#0c4a6e"),
        away: t("West Ham", "WHU", "#b91c1c", "#0891b2"),
        homeScore: 0,
        awayScore: 0,
        venue: "Amex Stadium",
      },
    ],
  },
  {
    id: "laliga",
    name: "LaLiga",
    country: "Spain",
    color: "#e11d48",
    matches: [
      {
        id: "ll-1",
        status: "live",
        minute: 81,
        day: 0,
        home: t("Barcelona", "BAR", "#3b82f6", "#7f1d1d"),
        away: t("Atlético", "ATM", "#f87171", "#1e3a8a"),
        homeScore: 1,
        awayScore: 1,
        venue: "Spotify Camp Nou",
        events: [
          { minute: 44, type: "goal", team: "home", player: "Lewandowski", detail: "Yamal" },
          { minute: 55, type: "yellow", team: "home", player: "Gündoğan" },
          { minute: 73, type: "goal", team: "away", player: "Griezmann", detail: "Penalty" },
        ],
        stats: [
          { label: "Possession", home: 64, away: 36, percent: true },
          { label: "Shots", home: 15, away: 7 },
          { label: "Shots on target", home: 5, away: 3 },
          { label: "Corners", home: 9, away: 2 },
          { label: "Fouls", home: 8, away: 14 },
        ],
      },
      {
        id: "ll-2",
        status: "finished",
        day: -1,
        home: t("Sevilla", "SEV", "#f1f5f9", "#dc2626"),
        away: t("Real Betis", "BET", "#4ade80", "#065f46"),
        homeScore: 0,
        awayScore: 1,
        venue: "Ramón Sánchez-Pizjuán",
        events: [
          { minute: 67, type: "goal", team: "away", player: "Isco", detail: "Fornals" },
          { minute: 84, type: "yellow", team: "home", player: "Navas" },
        ],
        stats: [
          { label: "Possession", home: 53, away: 47, percent: true },
          { label: "Shots", home: 12, away: 9 },
          { label: "Shots on target", home: 3, away: 4 },
          { label: "Corners", home: 6, away: 5 },
          { label: "Fouls", home: 11, away: 10 },
        ],
      },
      {
        id: "ll-3",
        status: "upcoming",
        kickoff: "22:00",
        day: 0,
        home: t("Real Sociedad", "RSO", "#60a5fa", "#dc2626"),
        away: t("Villarreal", "VIL", "#fde047", "#1d4ed8"),
        homeScore: 0,
        awayScore: 0,
        venue: "Reale Arena",
      },
    ],
  },
  {
    id: "seriea",
    name: "Serie A",
    country: "Italy",
    color: "#0ea5e9",
    matches: [
      {
        id: "sa-1",
        status: "live",
        minute: 39,
        day: 0,
        home: t("Juventus", "JUV", "#f8fafc", "#0f172a"),
        away: t("Napoli", "NAP", "#38bdf8", "#0c4a6e"),
        homeScore: 0,
        awayScore: 1,
        venue: "Allianz Stadium",
        events: [
          { minute: 21, type: "goal", team: "away", player: "Kvaratskhelia", detail: "Politano" },
          { minute: 35, type: "yellow", team: "home", player: "Locatelli" },
        ],
        stats: [
          { label: "Possession", home: 48, away: 52, percent: true },
          { label: "Shots", home: 6, away: 8 },
          { label: "Shots on target", home: 2, away: 4 },
          { label: "Corners", home: 3, away: 4 },
          { label: "Fouls", home: 7, away: 5 },
        ],
      },
      {
        id: "sa-2",
        status: "finished",
        day: -1,
        home: t("AC Milan", "MIL", "#ef4444", "#0f172a"),
        away: t("Roma", "ROM", "#facc15", "#7f1d1d"),
        homeScore: 3,
        awayScore: 0,
        venue: "San Siro",
        events: [
          { minute: 18, type: "goal", team: "home", player: "Leão", detail: "Pulisic" },
          { minute: 49, type: "goal", team: "home", player: "Giroud", detail: "Reijnders" },
          { minute: 71, type: "red", team: "away", player: "Cristante" },
          { minute: 83, type: "goal", team: "home", player: "Pulisic", detail: "Leão" },
        ],
        stats: [
          { label: "Possession", home: 58, away: 42, percent: true },
          { label: "Shots", home: 18, away: 5 },
          { label: "Shots on target", home: 9, away: 1 },
          { label: "Corners", home: 7, away: 2 },
          { label: "Fouls", home: 8, away: 13 },
        ],
      },
    ],
  },
  {
    id: "bundesliga",
    name: "Bundesliga",
    country: "Germany",
    color: "#dc2626",
    matches: [
      {
        id: "bl-1",
        status: "live",
        minute: 67,
        day: 0,
        home: t("Dortmund", "BVB", "#fde047", "#0f172a"),
        away: t("Leverkusen", "B04", "#f87171", "#0f172a"),
        homeScore: 2,
        awayScore: 3,
        venue: "Signal Iduna Park",
        events: [
          { minute: 6, type: "goal", team: "away", player: "Wirtz", detail: "Grimaldo" },
          { minute: 22, type: "goal", team: "home", player: "Adeyemi", detail: "Brandt" },
          { minute: 38, type: "goal", team: "away", player: "Boniface", detail: "Wirtz" },
          { minute: 44, type: "goal", team: "home", player: "Füllkrug", detail: "Penalty" },
          { minute: 59, type: "goal", team: "away", player: "Schick", detail: "Frimpong" },
          { minute: 63, type: "yellow", team: "home", player: "Can" },
        ],
        stats: [
          { label: "Possession", home: 44, away: 56, percent: true },
          { label: "Shots", home: 12, away: 16 },
          { label: "Shots on target", home: 5, away: 8 },
          { label: "Corners", home: 4, away: 6 },
          { label: "Fouls", home: 10, away: 8 },
        ],
      },
      {
        id: "bl-2",
        status: "upcoming",
        kickoff: "19:30",
        day: 1,
        home: t("RB Leipzig", "RBL", "#f87171", "#1e3a8a"),
        away: t("Stuttgart", "VfB", "#f1f5f9", "#dc2626"),
        homeScore: 0,
        awayScore: 0,
        venue: "Red Bull Arena",
      },
    ],
  },
  {
    id: "ligue1",
    name: "Ligue 1",
    country: "France",
    color: "#0891b2",
    matches: [
      {
        id: "l1-1",
        status: "finished",
        day: -1,
        home: t("Marseille", "OM", "#7dd3fc", "#0ea5e9"),
        away: t("Monaco", "ASM", "#ef4444", "#f8fafc"),
        homeScore: 1,
        awayScore: 2,
        venue: "Stade Vélodrome",
        events: [
          { minute: 25, type: "goal", team: "away", player: "Ben Yedder", detail: "Golovin" },
          { minute: 52, type: "goal", team: "home", player: "Aubameyang", detail: "Harit" },
          { minute: 79, type: "goal", team: "away", player: "Balogun", detail: "Fofana" },
          { minute: 90, type: "yellow", team: "home", player: "Veretout" },
        ],
        stats: [
          { label: "Possession", home: 55, away: 45, percent: true },
          { label: "Shots", home: 13, away: 10 },
          { label: "Shots on target", home: 4, away: 5 },
          { label: "Corners", home: 7, away: 4 },
          { label: "Fouls", home: 9, away: 12 },
        ],
      },
      {
        id: "l1-2",
        status: "upcoming",
        kickoff: "20:45",
        day: 1,
        home: t("Lyon", "OL", "#60a5fa", "#dc2626"),
        away: t("Lille", "LIL", "#dc2626", "#1e3a8a"),
        homeScore: 0,
        awayScore: 0,
        venue: "Groupama Stadium",
      },
    ],
  },
]
