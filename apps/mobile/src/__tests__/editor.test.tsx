import { fireEvent, render, screen, waitFor } from "@testing-library/react-native"
import * as ImagePicker from "expo-image-picker"
import { useLocalSearchParams } from "expo-router"

import EditorArticleScreen from "@/app/editor/[id]"
import { useAuth } from "@/hooks/use-auth"
import { api } from "@/lib/api"
import type { ArticleAdminOut } from "@/types/api"

jest.mock("expo-image-picker", () => ({
  requestMediaLibraryPermissionsAsync: jest.fn(),
  launchImageLibraryAsync: jest.fn(),
}))
jest.mock("@/hooks/use-auth", () => ({ useAuth: jest.fn() }))
jest.mock("@/lib/api", () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return {
    ApiError,
    api: {
      getEditorCategories: jest.fn(),
      getEditorArticle: jest.fn(),
      createArticle: jest.fn(),
      updateArticle: jest.fn(),
      setArticleStatus: jest.fn(),
      submitArticle: jest.fn(),
      withdrawArticle: jest.fn(),
      approveArticle: jest.fn(),
      rejectArticle: jest.fn(),
      scheduleArticle: jest.fn(),
      uploadMedia: jest.fn(),
    },
  }
})

const mockApi = api as unknown as Record<string, jest.Mock>
const picker = ImagePicker as unknown as Record<string, jest.Mock>
const params = useLocalSearchParams as unknown as jest.Mock
const mockUseAuth = useAuth as jest.Mock

const as = (id: number, role: string) => mockUseAuth.mockReturnValue({ user: { id, email: "x@y.z", display_name: "X", role }, loading: false })

const article = (over: Partial<ArticleAdminOut> = {}): ArticleAdminOut =>
  ({
    id: 5, slug: "story", title: "A story", excerpt: "Short", featured_image_url: null, featured_image_alt: null, published_at: null,
    category: null, author_name: "Alice", tags: [], relation: null, reason: null, content: "<p>Body text</p>", content_text: "Body text",
    content_blocks: [{ type: "paragraph", text: "Body text" }], updated_at: "2026-10-08T10:00:00Z", view_count: 0, canonical_path: "/article/story",
    teams: [], players: [], competitions: [], matches: [], gallery: [], status: "draft", is_featured: false, author_id: 10,
    publish_at: null, unpublish_at: null, review_note: null, featured_media_id: null, ...over,
  }) as ArticleAdminOut

const names = () => screen.queryAllByRole("button").map((b) => b.props.accessibilityLabel ?? "")

beforeEach(() => {
  for (const fn of [...Object.values(mockApi), ...Object.values(picker)]) if (typeof fn === "function") fn.mockReset()
  mockApi.getEditorCategories.mockResolvedValue([])
  params.mockReturnValue({ id: "5" })
})

const hasButton = (label: string) => screen.queryByText(label) !== null

describe("mobile editor respects the editorial workflow", () => {
  it("an author with their own draft can save and submit, but not publish", async () => {
    as(10, "author")
    mockApi.getEditorArticle.mockResolvedValue(article())
    await render(<EditorArticleScreen />)
    expect(await screen.findByText("Save changes")).toBeTruthy()
    expect(hasButton("Submit for review")).toBe(true)
    for (const forbidden of ["Publish now", "Schedule", "Approve & publish", "Request changes", "Archive", "Unpublish"]) {
      expect(hasButton(forbidden)).toBe(false)
    }
    expect(screen.queryByLabelText("Publish at")).toBeNull() // scheduling is an editor tool
  })

  it("submitting saves first, then moves it to review", async () => {
    as(10, "author")
    mockApi.getEditorArticle.mockResolvedValue(article())
    mockApi.updateArticle.mockResolvedValue(article())
    mockApi.submitArticle.mockResolvedValue(article({ status: "in_review" }))
    await render(<EditorArticleScreen />)
    await fireEvent.press(await screen.findByText("Submit for review"))
    await waitFor(() => expect(mockApi.submitArticle).toHaveBeenCalledWith(5))
    expect(mockApi.updateArticle).toHaveBeenCalled()
    expect(await screen.findByText("Submitted for review.")).toBeTruthy()
    expect(await screen.findByText(/Waiting for an editor/)).toBeTruthy()
  })

  it("an author whose article is in review can only read it or withdraw it", async () => {
    as(10, "author")
    mockApi.getEditorArticle.mockResolvedValue(article({ status: "in_review" }))
    await render(<EditorArticleScreen />)
    expect(await screen.findByText(/can read this article but not change it/)).toBeTruthy()
    expect(hasButton("Withdraw from review")).toBe(true)
    expect(hasButton("Save changes")).toBe(false)
    expect(screen.getByLabelText("Headline").props.editable).toBe(false)
  })

  it("an editor reviewing someone else's piece can approve it or send it back with a note", async () => {
    as(20, "editor")
    mockApi.getEditorArticle.mockResolvedValue(article({ status: "in_review" }))
    mockApi.rejectArticle.mockResolvedValue(article({ status: "draft", review_note: "Check the score" }))
    await render(<EditorArticleScreen />)
    expect(await screen.findByText("Approve & publish")).toBeTruthy()
    expect(screen.getByLabelText("Publish at")).toBeTruthy()
    await fireEvent.press(screen.getByText("Request changes"))
    await fireEvent.changeText(screen.getByLabelText("What should the author change?"), "Check the score")
    await fireEvent.press(screen.getByText("Send back to author"))
    await waitFor(() => expect(mockApi.rejectArticle).toHaveBeenCalledWith(5, "Check the score"))
    expect(await screen.findByText(/Changes requested: Check the score/)).toBeTruthy()
  })

  it("approving with a time schedules instead of publishing", async () => {
    as(20, "editor")
    mockApi.getEditorArticle.mockResolvedValue(article({ status: "in_review" }))
    mockApi.updateArticle.mockResolvedValue(article({ status: "in_review" }))
    mockApi.approveArticle.mockResolvedValue(article({ status: "scheduled" }))
    await render(<EditorArticleScreen />)
    await fireEvent.changeText(await screen.findByLabelText("Publish at"), "2099-01-01 10:00")
    expect(screen.getByText("Approve & schedule")).toBeTruthy()
    await fireEvent.press(screen.getByText("Approve & schedule"))
    await waitFor(() => expect(mockApi.approveArticle).toHaveBeenCalled())
    const [, body] = mockApi.approveArticle.mock.calls[0]
    expect(typeof body.publish_at).toBe("string")
    expect(await screen.findByText("Approved and scheduled.")).toBeTruthy()
  })

  it("scheduling rejects a time in the past before calling the API", async () => {
    as(20, "editor")
    mockApi.getEditorArticle.mockResolvedValue(article())
    await render(<EditorArticleScreen />)
    await fireEvent.changeText(await screen.findByLabelText("Publish at"), "2001-01-01 10:00")
    await fireEvent.press(screen.getByText("Schedule"))
    expect(await screen.findByText(/must be in the future/)).toBeTruthy()
    expect(mockApi.scheduleArticle).not.toHaveBeenCalled()
  })

  it("a published article offers unpublish and archive to editors", async () => {
    as(20, "admin")
    mockApi.getEditorArticle.mockResolvedValue(article({ status: "published", published_at: "2026-10-01T00:00:00Z" }))
    await render(<EditorArticleScreen />)
    expect(await screen.findByText("Unpublish")).toBeTruthy()
    expect(hasButton("Archive")).toBe(true)
    expect(hasButton("Submit for review")).toBe(false)
  })

  it("someone without a staff role gets no editor at all", async () => {
    as(1, "user")
    await render(<EditorArticleScreen />)
    expect(await screen.findByText(/need a writer or editor account/)).toBeTruthy()
    expect(mockApi.getEditorArticle).not.toHaveBeenCalled()
  })
})

describe("mobile editor uploads and preview", () => {
  it("uploads a picked image and attaches it as the featured image", async () => {
    as(10, "author")
    params.mockReturnValue({ id: "new" })
    picker.requestMediaLibraryPermissionsAsync.mockResolvedValue({ granted: true })
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: false, assets: [{ uri: "file:///p.jpg", fileName: "p.jpg", mimeType: "image/jpeg", fileSize: 120000 }] })
    mockApi.uploadMedia.mockResolvedValue({ id: 8, url: "http://api/media/x/large", thumb_url: "http://api/media/x/thumb" })
    await render(<EditorArticleScreen />)
    await fireEvent.press(await screen.findByText("Upload an image"))
    await waitFor(() => expect(mockApi.uploadMedia).toHaveBeenCalled())
    expect(mockApi.uploadMedia.mock.calls[0][0]).toEqual({ uri: "file:///p.jpg", name: "p.jpg", type: "image/jpeg" })
    expect(await screen.findByText(/Uploaded \(117 KB\)/)).toBeTruthy()
    expect(await screen.findByText("Replace image")).toBeTruthy()
  })

  it("refuses unsupported or oversized pictures before uploading", async () => {
    as(10, "author")
    params.mockReturnValue({ id: "new" })
    picker.requestMediaLibraryPermissionsAsync.mockResolvedValue({ granted: true })
    picker.launchImageLibraryAsync.mockResolvedValue({ canceled: false, assets: [{ uri: "file:///a.svg", fileName: "a.svg", mimeType: "image/svg+xml", fileSize: 100 }] })
    await render(<EditorArticleScreen />)
    await fireEvent.press(await screen.findByText("Upload an image"))
    expect(await screen.findByText(/only JPEG, PNG, WebP and GIF/)).toBeTruthy()
    expect(mockApi.uploadMedia).not.toHaveBeenCalled()
  })

  it("explains when photo access is denied and never opens the picker", async () => {
    as(10, "author")
    params.mockReturnValue({ id: "new" })
    picker.requestMediaLibraryPermissionsAsync.mockResolvedValue({ granted: false })
    await render(<EditorArticleScreen />)
    await fireEvent.press(await screen.findByText("Upload an image"))
    expect(await screen.findByText(/Allow photo access/)).toBeTruthy()
    expect(picker.launchImageLibraryAsync).not.toHaveBeenCalled()
  })

  it("previews the last saved version from the server's blocks", async () => {
    as(10, "author")
    mockApi.getEditorArticle.mockResolvedValue(article({ title: "Preview me", content_blocks: [{ type: "heading", text: "Big heading" }, { type: "paragraph", text: "Para" }] }))
    await render(<EditorArticleScreen />)
    await fireEvent.press(await screen.findByRole("tab", { name: "Preview" }))
    expect(await screen.findByText("Big heading")).toBeTruthy()
    expect(screen.getByText(/Preview — last saved version, not public/)).toBeTruthy()
    expect(names().length).toBeGreaterThanOrEqual(0)
  })

  it("a new article must be saved before it can be previewed", async () => {
    as(10, "author")
    params.mockReturnValue({ id: "new" })
    await render(<EditorArticleScreen />)
    await fireEvent.press(await screen.findByRole("tab", { name: "Preview" }))
    expect(await screen.findByText("Save the article first to preview it.")).toBeTruthy()
  })
})
