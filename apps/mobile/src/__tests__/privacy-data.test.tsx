import { fireEvent, render, screen, waitFor } from "@testing-library/react-native"
import { Share } from "react-native"

import { PrivacyData } from "@/components/privacy-data"
import { ApiError, api } from "@/lib/api"

const mockLogout = jest.fn(async () => undefined)
jest.mock("@/hooks/use-auth", () => ({ useAuth: () => ({ logout: mockLogout }) }))
jest.mock("@/lib/api", () => {
  class MockApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return {
    ApiError: MockApiError,
    api: { exportMyData: jest.fn(), deleteAccount: jest.fn() },
  }
})

const exportMyData = api.exportMyData as jest.Mock
const deleteAccount = api.deleteAccount as jest.Mock

beforeEach(() => {
  jest.clearAllMocks()
})

describe("PrivacyData", () => {
  it("shares the export the API returns", async () => {
    exportMyData.mockResolvedValue({ account: { id: 7 } })
    const share = jest.spyOn(Share, "share").mockResolvedValue({ action: "sharedAction" } as never)
    await render(<PrivacyData />)

    await fireEvent.press(screen.getByText("Download my data"))

    await waitFor(() => expect(share).toHaveBeenCalledTimes(1))
    expect(share.mock.calls[0][0].message).toContain('"id": 7')
    expect(await screen.findByText("Your data is ready to save or send.")).toBeTruthy()
  })

  it("will not delete until the person has asked, typed a password and confirmed", async () => {
    await render(<PrivacyData />)

    expect(screen.queryByText("Delete forever")).toBeNull()
    await fireEvent.press(screen.getByText("Delete my account…"))
    expect(screen.getByText("Delete forever")).toBeTruthy()
    await fireEvent.press(screen.getByText("Delete forever")) // no password yet: disabled
    expect(deleteAccount).not.toHaveBeenCalled()
  })

  it("sends the password to the server and signs the device out when the account is erased", async () => {
    deleteAccount.mockResolvedValue(undefined)
    await render(<PrivacyData />)

    await fireEvent.press(screen.getByText("Delete my account…"))
    await fireEvent.changeText(screen.getByLabelText("Password to confirm account deletion"), "Sup3rSecret!")
    await fireEvent.press(screen.getByText("Delete forever"))

    await waitFor(() => expect(deleteAccount).toHaveBeenCalledWith("Sup3rSecret!"))
    await waitFor(() => expect(mockLogout).toHaveBeenCalledTimes(1))
  })

  it("keeps the account and shows the server's reason when the password is wrong", async () => {
    deleteAccount.mockRejectedValue(new ApiError(400, "Password is incorrect."))
    await render(<PrivacyData />)

    await fireEvent.press(screen.getByText("Delete my account…"))
    await fireEvent.changeText(screen.getByLabelText("Password to confirm account deletion"), "nope")
    await fireEvent.press(screen.getByText("Delete forever"))

    expect(await screen.findByText("Password is incorrect.")).toBeTruthy()
    expect(mockLogout).not.toHaveBeenCalled()
  })

  it("cancelling clears the password and hides the confirmation", async () => {
    await render(<PrivacyData />)
    await fireEvent.press(screen.getByText("Delete my account…"))
    await fireEvent.changeText(screen.getByLabelText("Password to confirm account deletion"), "typed")
    await fireEvent.press(screen.getByText("Cancel"))
    expect(screen.queryByLabelText("Password to confirm account deletion")).toBeNull()
    expect(deleteAccount).not.toHaveBeenCalled()
  })
})
