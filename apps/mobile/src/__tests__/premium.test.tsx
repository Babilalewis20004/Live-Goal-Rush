import { fireEvent, render, screen, waitFor } from "@testing-library/react-native"
import { Alert, Linking } from "react-native"

import { ReportProfile } from "@/components/community/report-profile"
import PremiumScreen from "@/app/premium"
import { useAuth } from "@/hooks/use-auth"
import { api } from "@/lib/api"
import type { SubscriptionOut } from "@/types/api"

jest.mock("@/hooks/use-auth", () => ({ useAuth: jest.fn() }))
jest.mock("@/lib/api", () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return { ApiError, api: { getPlans: jest.fn(), getSubscription: jest.fn(), cancelSubscription: jest.fn(), reportProfile: jest.fn() } }
})

const mockApi = api as unknown as Record<string, jest.Mock>
const mockUseAuth = useAuth as jest.Mock
const signedIn = () => mockUseAuth.mockReturnValue({ user: { id: 7, role: "user" }, loading: false })
const sub = (over: Partial<SubscriptionOut> = {}): SubscriptionOut => ({ status: "none", plan: null, entitlements: [], current_period_end: null, cancel_at_period_end: false, ...over })

beforeEach(() => {
  for (const fn of Object.values(mockApi)) fn.mockReset()
  mockApi.getPlans.mockResolvedValue([
    { code: "premium_monthly", name: "Premium (monthly)", interval: "month", price_minor: 499, currency: "GBP", entitlements: [] },
    { code: "premium_yearly", name: "Premium (yearly)", interval: "year", price_minor: 3999, currency: "GBP", entitlements: [] },
  ])
  signedIn()
})

describe("Premium screen", () => {
  it("shows what is free, what Premium adds, and the plan prices", async () => {
    mockApi.getSubscription.mockResolvedValue(sub())
    await render(<PremiumScreen />)
    expect(await screen.findByLabelText("Premium (monthly), £4.99 / month")).toBeTruthy()
    expect(screen.getByLabelText("Premium (yearly), £39.99 / year")).toBeTruthy()
    expect(screen.getByText(/Livescores and real-time match updates/)).toBeTruthy()
    expect(screen.getByText(/You're on the free plan\./)).toBeTruthy()
    expect(screen.getByText(/not betting advice/)).toBeTruthy()
  })

  it("sends a free user to the website to subscribe (no card details in the app)", async () => {
    mockApi.getSubscription.mockResolvedValue(sub())
    const open = jest.spyOn(Linking, "openURL").mockResolvedValue(true)
    await render(<PremiumScreen />)
    await fireEvent.press(await screen.findByRole("button", { name: "Subscribe on the website" }))
    expect(open).toHaveBeenCalledWith(expect.stringMatching(/\/premium$/))
  })

  it("lets a subscriber cancel after confirming, and says Premium continues until the period ends", async () => {
    mockApi.getSubscription.mockResolvedValue(sub({ status: "active", plan: "premium_monthly", entitlements: ["advanced_analytics"], current_period_end: "2026-11-01T00:00:00Z" }))
    mockApi.cancelSubscription.mockResolvedValue(sub({ status: "cancelled", entitlements: ["advanced_analytics"], cancel_at_period_end: true }))
    const alert = jest.spyOn(Alert, "alert").mockImplementation(() => {})
    await render(<PremiumScreen />)
    expect(await screen.findByText("Premium is active. Renews on 1 Nov 2026.")).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Subscribe on the website" })).toBeNull()
    await fireEvent.press(screen.getByRole("button", { name: "Cancel subscription" }))
    expect(mockApi.cancelSubscription).not.toHaveBeenCalled() // asks first
    const buttons = alert.mock.calls[0][2] as { text: string; onPress?: () => void }[]
    expect(alert.mock.calls[0][1]).toMatch(/keep Premium until the end/)
    buttons.find((b) => b.text === "Cancel subscription")!.onPress!()
    await waitFor(() => expect(mockApi.cancelSubscription).toHaveBeenCalled())
  })

  it("asks a signed-out visitor to sign in rather than showing a subscribe button", async () => {
    mockUseAuth.mockReturnValue({ user: null, loading: false })
    await render(<PremiumScreen />)
    expect(await screen.findByRole("button", { name: "Sign in to subscribe" })).toBeTruthy()
    expect(mockApi.getSubscription).not.toHaveBeenCalled()
  })
})

describe("ReportProfile", () => {
  it("needs sign-in, and reports with an optional reason once", async () => {
    mockUseAuth.mockReturnValue({ user: null, loading: false })
    const { unmount } = await render(<ReportProfile userId={3} />)
    expect(screen.getByRole("button", { name: "Sign in to report this profile" })).toBeTruthy()
    await unmount()

    signedIn()
    mockApi.reportProfile.mockResolvedValue(undefined)
    await render(<ReportProfile userId={3} />)
    await fireEvent.press(screen.getByRole("button", { name: "Report this profile" }))
    await fireEvent.changeText(screen.getByLabelText("Why are you reporting this profile?"), "offensive bio")
    await fireEvent.press(screen.getByRole("button", { name: "Send report" }))
    await waitFor(() => expect(mockApi.reportProfile).toHaveBeenCalledWith(3, "offensive bio"))
    expect(await screen.findByText(/a moderator will take a look/)).toBeTruthy()
  })

  it("never offers you a way to report yourself", async () => {
    signedIn()
    await render(<ReportProfile userId={7} />)
    expect(screen.queryByRole("button", { name: "Report this profile" })).toBeNull()
  })
})
