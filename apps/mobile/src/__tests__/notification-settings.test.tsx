import { fireEvent, render, screen, waitFor } from "@testing-library/react-native"

import NotificationSettingsScreen from "@/app/notification-settings"
import { OverrideControl } from "@/components/override-control"
import { SeasonChips } from "@/components/match-centre/season-chips"
import { api } from "@/lib/api"
import type { FavouritesOut, NotificationPreferenceOut } from "@/types/api"

jest.mock("@/lib/api", () => ({
  api: {
    getNotificationPreferences: jest.fn(),
    getFavourites: jest.fn(),
    updateNotificationPreference: jest.fn(),
    resetNotificationPreference: jest.fn(),
  },
}))
jest.mock("@/lib/push-notifications", () => ({ registerForPushNotificationsAsync: jest.fn() }))

const mockApi = api as unknown as Record<
  "getNotificationPreferences" | "getFavourites" | "updateNotificationPreference" | "resetNotificationPreference",
  jest.Mock
>

const TEAM = { id: 5, name: "Arsenal", short_name: "ARS", country: null, logo_url: null }
const FAVOURITES: FavouritesOut = {
  teams: [{ id: 1, created_at: "", team: TEAM }],
  competitions: [],
  matches: [],
}
let nextId = 100
const pref = (
  scope_type: NotificationPreferenceOut["scope_type"],
  scope_id: number | null,
  event_type: NotificationPreferenceOut["event_type"],
  enabled: boolean,
): NotificationPreferenceOut => ({ id: nextId++, scope_type, scope_id, event_type, enabled })

beforeEach(() => {
  for (const fn of Object.values(mockApi)) fn.mockReset()
  mockApi.getNotificationPreferences.mockResolvedValue([])
  mockApi.getFavourites.mockResolvedValue(FAVOURITES)
})

async function openArsenal() {
  await render(<NotificationSettingsScreen />)
  const header = await screen.findByRole("button", { name: /Arsenal, default settings/ })
  await fireEvent.press(header)
}

describe("per-favourite notification settings", () => {
  it("lists followed teams and explains how the choices combine", async () => {
    await render(<NotificationSettingsScreen />)
    expect(await screen.findByText("Arsenal")).toBeTruthy()
    expect(screen.getByText(/You're notified if any favourite that covers a match allows the event/)).toBeTruthy()
  })

  it("says so when there's nothing followed yet", async () => {
    mockApi.getFavourites.mockResolvedValue({ teams: [], competitions: [], matches: [] })
    await render(<NotificationSettingsScreen />)
    expect(await screen.findByText(/Follow a team, competition or match and it will appear here/)).toBeTruthy()
  })

  it("expanding a favourite shows each event as Default / On / Off, all starting on Default", async () => {
    await openArsenal()
    // 5 notifiable events x (Default, On, Off); the group container itself is
    // deliberately not an accessible element, so its radios stay individually focusable
    expect(screen.getAllByRole("radio")).toHaveLength(15)
    expect(screen.getByRole("radio", { name: "Arsenal Goals: Default", checked: true })).toBeTruthy()
    expect(screen.getAllByText("Notify (default)")).toHaveLength(5)
  })

  it("choosing Off saves a team-scoped override for that event and shows it as custom", async () => {
    mockApi.updateNotificationPreference.mockResolvedValue(pref("team", 5, "GOAL", false))
    await openArsenal()
    await fireEvent.press(screen.getByRole("radio", { name: "Arsenal Goals: Off" }))

    await waitFor(() =>
      expect(mockApi.updateNotificationPreference).toHaveBeenCalledWith("team", 5, "GOAL", false),
    )
    expect(await screen.findByRole("radio", { name: "Arsenal Goals: Off", checked: true })).toBeTruthy()
    expect(screen.getByRole("button", { name: /Arsenal, 1 custom settings/ })).toBeTruthy()
    expect(screen.getByText(/Don't notify for this/)).toBeTruthy()
  })

  it("choosing Default removes the override on the server", async () => {
    mockApi.getNotificationPreferences.mockResolvedValue([pref("team", 5, "CARD", false)])
    mockApi.resetNotificationPreference.mockResolvedValue(undefined)
    await render(<NotificationSettingsScreen />)
    await fireEvent.press(await screen.findByRole("button", { name: /Arsenal, 1 custom settings/ }))
    await fireEvent.press(screen.getByRole("radio", { name: "Arsenal Cards: Default" }))

    await waitFor(() => expect(mockApi.resetNotificationPreference).toHaveBeenCalledWith("team", 5, "CARD"))
    expect(await screen.findByRole("button", { name: /Arsenal, default settings/ })).toBeTruthy()
    expect(mockApi.updateNotificationPreference).not.toHaveBeenCalled()
  })

  it("a failed save leaves the old choice selected and shows an error", async () => {
    mockApi.updateNotificationPreference.mockRejectedValue(new Error("boom"))
    await openArsenal()
    await fireEvent.press(screen.getByRole("radio", { name: "Arsenal Goals: On" }))
    expect(await screen.findByRole("alert")).toBeTruthy()
    expect(screen.getByRole("radio", { name: "Arsenal Goals: Default", checked: true })).toBeTruthy()
  })

  it("a global mute is called out: it wins over any per-favourite choice", async () => {
    mockApi.getNotificationPreferences.mockResolvedValue([pref("global", null, "GOAL", false)])
    await openArsenal()
    expect(screen.getAllByText("Silenced everywhere by your global setting").length).toBeGreaterThanOrEqual(1)
  })

  it("still works if favourites can't be loaded (the global toggles remain)", async () => {
    mockApi.getFavourites.mockRejectedValue(new Error("offline"))
    await render(<NotificationSettingsScreen />)
    expect(await screen.findByText("What you get notified about")).toBeTruthy()
    expect(screen.getByText(/Follow a team, competition or match/)).toBeTruthy()
  })
})

describe("OverrideControl", () => {
  it("is a radio group whose selected option is exposed, and reports changes", async () => {
    const onChange = jest.fn()
    await render(<OverrideControl label="Goals" state="on" onChange={onChange} />)
    expect(screen.getByRole("radio", { name: "Goals: On", checked: true })).toBeTruthy()
    await fireEvent.press(screen.getByRole("radio", { name: "Goals: Off" }))
    expect(onChange).toHaveBeenCalledWith("off")
  })
})

describe("SeasonChips", () => {
  const info = { current: "2026/27", seasons: ["2026/27", "2025/26"], historical_supported: true }

  it("offers stored seasons plus earlier on-demand ones, marking the current one", async () => {
    await render(<SeasonChips info={info} value={null} onChange={() => {}} />)
    expect(screen.getByRole("radio", { name: "Season 2026/27, current", checked: true })).toBeTruthy()
    expect(screen.getByRole("radio", { name: "Season 2025/26" })).toBeTruthy()
    expect(screen.getByRole("radio", { name: "Season 2024/25, load from provider" })).toBeTruthy()
  })

  it("choosing the current season reports null (restore the server data)", async () => {
    const onChange = jest.fn()
    await render(<SeasonChips info={info} value="2025/26" onChange={onChange} />)
    await fireEvent.press(screen.getByRole("radio", { name: "Season 2026/27, current" }))
    expect(onChange).toHaveBeenCalledWith(null)
    await fireEvent.press(screen.getByRole("radio", { name: "Season 2024/25, load from provider" }))
    expect(onChange).toHaveBeenCalledWith("2024/25")
  })

  it("renders nothing when there's only one season and no history to offer", async () => {
    await render(
      <SeasonChips info={{ current: "2026/27", seasons: ["2026/27"], historical_supported: false }} value={null} onChange={() => {}} />,
    )
    expect(screen.queryByText("Season")).toBeNull()
  })
})

