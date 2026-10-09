import { fireEvent, render, screen, waitFor } from "@testing-library/react-native"

import { CommentsSection } from "@/components/community/comments-section"
import { PollCard } from "@/components/community/poll-card"
import { ReactionsBar } from "@/components/community/reactions-bar"
import { useAuth } from "@/hooks/use-auth"
import { api } from "@/lib/api"
import type { CommentOut, CommentPage, PollOut, ReactionSummary } from "@/types/api"

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
      getReactions: jest.fn(),
      react: jest.fn(),
      unreact: jest.fn(),
      getPoll: jest.fn(),
      votePoll: jest.fn(),
      getComments: jest.fn(),
      postComment: jest.fn(),
      editComment: jest.fn(),
      deleteComment: jest.fn(),
      likeComment: jest.fn(),
      unlikeComment: jest.fn(),
      reportComment: jest.fn(),
    },
  }
})

const mockApi = api as unknown as Record<string, jest.Mock>
const mockUseAuth = useAuth as jest.Mock
const signedIn = (role = "user") => mockUseAuth.mockReturnValue({ user: { id: 1, email: "a@b.c", display_name: "Me", role }, loading: false })
const signedOut = () => mockUseAuth.mockReturnValue({ user: null, loading: false })

beforeEach(() => {
  for (const fn of Object.values(mockApi)) fn.mockReset()
  signedOut()
})

// -- reactions ---------------------------------------------------------------------------------

const reactions = (over: Partial<ReactionSummary> = {}): ReactionSummary => ({
  counts: { thumbs_up: 0, fire: 2, wow: 0, goal: 0, heart: 0, laugh: 0, clap: 0 },
  total: 2,
  mine: null,
  ...over,
})

describe("ReactionsBar", () => {
  it("shows public counts to everyone and asks signed-out users to sign in instead of reacting", async () => {
    mockApi.getReactions.mockResolvedValue(reactions())
    await render(<ReactionsBar targetType="article" targetId={5} />)
    const fire = await screen.findByRole("button", { name: "Fire, 2 reactions" })
    await fireEvent.press(fire)
    expect(mockApi.react).not.toHaveBeenCalled()
    expect(await screen.findByText(/to react\./)).toBeTruthy()
  })

  it("reacts optimistically, then keeps the server's answer", async () => {
    signedIn()
    mockApi.getReactions.mockResolvedValue(reactions())
    mockApi.react.mockResolvedValue(reactions({ counts: { thumbs_up: 0, fire: 3, wow: 0, goal: 0, heart: 0, laugh: 0, clap: 0 }, total: 3, mine: "fire" }))
    await render(<ReactionsBar targetType="article" targetId={5} />)
    await fireEvent.press(await screen.findByRole("button", { name: "Fire, 2 reactions" }))
    expect(mockApi.react).toHaveBeenCalledWith("article", 5, "fire")
    expect(await screen.findByRole("button", { name: "Fire, 3 reactions, your reaction" })).toBeTruthy()
  })

  it("tapping your own reaction removes it, and a failure puts the count back", async () => {
    signedIn()
    mockApi.getReactions.mockResolvedValue(reactions({ mine: "fire" }))
    mockApi.unreact.mockRejectedValue(new Error("offline"))
    await render(<ReactionsBar targetType="match" targetId={9} />)
    await fireEvent.press(await screen.findByRole("button", { name: "Fire, 2 reactions, your reaction" }))
    expect(mockApi.unreact).toHaveBeenCalledWith("match", 9)
    expect(await screen.findByText("Couldn't save your reaction.")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Fire, 2 reactions, your reaction" })).toBeTruthy()
  })
})

// -- polls ----------------------------------------------------------------------------------------

const poll = (over: Partial<PollOut> = {}): PollOut => ({
  id: 3,
  question: "Who wins the derby?",
  kind: "question",
  status: "open",
  match_id: null,
  article_id: null,
  closes_at: null,
  total_votes: 3,
  options: [
    { id: 1, label: "Red", votes: 2, percent: 66.7 },
    { id: 2, label: "Blue", votes: 1, percent: 33.3 },
  ],
  my_vote: null,
  winner_option_id: null,
  ...over,
})

describe("PollCard", () => {
  it("lets a signed-in user pick an option and vote once, then shows results in words", async () => {
    signedIn()
    mockApi.getPoll.mockResolvedValue(poll())
    mockApi.votePoll.mockResolvedValue(poll({ my_vote: 2, total_votes: 4, options: [{ id: 1, label: "Red", votes: 2, percent: 50 }, { id: 2, label: "Blue", votes: 2, percent: 50 }] }))
    await render(<PollCard poll={poll()} />)
    expect(screen.getByRole("button", { name: "Vote" }).props.accessibilityState?.disabled ?? screen.getByRole("button", { name: "Vote" }).props.disabled).toBeTruthy()
    await fireEvent.press(screen.getByRole("radio", { name: "Blue" }))
    await fireEvent.press(screen.getByRole("button", { name: "Vote" }))
    expect(mockApi.votePoll).toHaveBeenCalledWith(3, 2)
    expect(await screen.findByLabelText(/Blue: 50 percent, 2 votes, your vote/)).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Vote" })).toBeNull() // cannot vote twice
  })

  it("shows results but no voting to someone signed out, and tells them why", async () => {
    await render(<PollCard poll={poll()} />)
    expect(screen.getByRole("radio", { name: "Red" }).props.accessibilityState.disabled).toBe(true)
    expect(screen.getByText(/to vote\./)).toBeTruthy()
    expect(screen.getByText("3 votes")).toBeTruthy()
  })

  it("a closed poll shows the result and the winner and offers no vote", async () => {
    signedIn()
    const closed = poll({ status: "closed", winner_option_id: 1 })
    mockApi.getPoll.mockResolvedValue(closed)
    await render(<PollCard poll={closed} />)
    expect(screen.getByLabelText(/Red: 66.7 percent, 2 votes, winner/)).toBeTruthy()
    expect(screen.getByText(/Closed/)).toBeTruthy()
    expect(screen.getByText("Result: Red")).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Vote" })).toBeNull()
  })

  it("explains a refused vote (e.g. already voted elsewhere)", async () => {
    signedIn()
    const { ApiError } = jest.requireMock("@/lib/api")
    mockApi.getPoll.mockResolvedValue(poll())
    mockApi.votePoll.mockRejectedValue(new ApiError(409, "You have already voted in this poll."))
    await render(<PollCard poll={poll()} />)
    await fireEvent.press(screen.getByRole("radio", { name: "Red" }))
    await fireEvent.press(screen.getByRole("button", { name: "Vote" }))
    expect(await screen.findByText("You have already voted in this poll.")).toBeTruthy()
  })
})

// -- comments -------------------------------------------------------------------------------------------

const comment = (id: number, over: Partial<CommentOut> = {}): CommentOut => ({
  id,
  author: { id: 50 + id, display_name: `User${id}`, profile_public: false },
  body: `Body ${id}`,
  created_at: new Date().toISOString(),
  edited_at: null,
  like_count: 0,
  reply_count: 0,
  removed: false,
  parent_id: null,
  liked_by_me: false,
  mine: false,
  replies: [],
  ...over,
})

const page = (items: CommentOut[], total = items.length): CommentPage => ({ items, total, total_comments: total, page: 1, page_size: 20 })

describe("CommentsSection", () => {
  it("lets anyone read but asks signed-out users to sign in to comment", async () => {
    mockApi.getComments.mockResolvedValue(page([comment(1)]))
    await render(<CommentsSection targetType="article" targetId={5} />)
    expect(await screen.findByText("Body 1")).toBeTruthy()
    expect(screen.getByText(/to join the conversation\./)).toBeTruthy()
    expect(screen.queryByLabelText("Add a comment")).toBeNull()
  })

  it("renders comment bodies as plain text, never as markup", async () => {
    const evil = "<script>alert(1)</script><b>bold?</b>"
    mockApi.getComments.mockResolvedValue(page([comment(1, { body: evil })]))
    await render(<CommentsSection targetType="article" targetId={5} />)
    expect(await screen.findByText(evil)).toBeTruthy()
  })

  it("posts a comment, shows it at once, and validates before sending", async () => {
    signedIn()
    mockApi.getComments.mockResolvedValue(page([]))
    mockApi.postComment.mockResolvedValue(comment(9, { body: "My take", author: { id: 1, display_name: "Me", profile_public: false }, mine: true }))
    await render(<CommentsSection targetType="article" targetId={5} />)
    expect(await screen.findByText("No comments yet. Be the first.")).toBeTruthy()

    await fireEvent.changeText(screen.getByLabelText("Add a comment"), "https://a.example https://b.example https://c.example")
    await fireEvent.press(screen.getByRole("button", { name: "Post" }))
    expect(await screen.findByText(/at most 2 links/)).toBeTruthy()
    expect(mockApi.postComment).not.toHaveBeenCalled()

    await fireEvent.changeText(screen.getByLabelText("Add a comment"), "My take")
    await fireEvent.press(screen.getByRole("button", { name: "Post" }))
    expect(await screen.findByText("My take")).toBeTruthy()
    expect(mockApi.postComment).toHaveBeenCalledWith("article", 5, "My take")
  })

  it("shows the server's reason when posting is refused", async () => {
    signedIn()
    const { ApiError } = jest.requireMock("@/lib/api")
    mockApi.getComments.mockResolvedValue(page([]))
    mockApi.postComment.mockRejectedValue(new ApiError(429, "You're doing that too fast. Please wait a moment."))
    await render(<CommentsSection targetType="match" targetId={7} />)
    await fireEvent.changeText(await screen.findByLabelText("Add a comment"), "Again")
    await fireEvent.press(screen.getByRole("button", { name: "Post" }))
    expect(await screen.findByText(/too fast/)).toBeTruthy()
  })

  it("likes optimistically and rolls back if it fails", async () => {
    signedIn()
    mockApi.getComments.mockResolvedValue(page([comment(1, { like_count: 4 })]))
    mockApi.likeComment.mockRejectedValue(new Error("offline"))
    await render(<CommentsSection targetType="article" targetId={5} />)
    await fireEvent.press(await screen.findByRole("button", { name: "Like comment by User1, 4 likes" }))
    expect(mockApi.likeComment).toHaveBeenCalledWith(1)
    expect(await screen.findByText("Couldn't save your like.")).toBeTruthy()
    expect(screen.getByRole("button", { name: "Like comment by User1, 4 likes" })).toBeTruthy()
  })

  it("offers edit/delete on your own comments and report on others'", async () => {
    signedIn()
    mockApi.getComments.mockResolvedValue(page([comment(1, { mine: true }), comment(2)]))
    await render(<CommentsSection targetType="article" targetId={5} />)
    await screen.findByText("Body 1")
    expect(screen.getByRole("button", { name: "Edit comment by User1" })).toBeTruthy()
    expect(screen.getByRole("button", { name: "Delete comment by User1" })).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Report comment by User1" })).toBeNull()
    expect(screen.getByRole("button", { name: "Report comment by User2" })).toBeTruthy()
    expect(screen.queryByRole("button", { name: "Edit comment by User2" })).toBeNull()
    expect(screen.queryByRole("button", { name: "Delete comment by User2" })).toBeNull()
  })

  it("moderators can delete anyone's comment", async () => {
    signedIn("editor")
    mockApi.getComments.mockResolvedValue(page([comment(2)]))
    await render(<CommentsSection targetType="article" targetId={5} />)
    expect(await screen.findByRole("button", { name: "Delete comment by User2" })).toBeTruthy()
  })

  it("asks before deleting, then removes the comment", async () => {
    signedIn()
    mockApi.getComments.mockResolvedValue(page([comment(1, { mine: true })]))
    mockApi.deleteComment.mockResolvedValue(undefined)
    await render(<CommentsSection targetType="article" targetId={5} />)
    await fireEvent.press(await screen.findByRole("button", { name: "Delete comment by User1" }))
    expect(mockApi.deleteComment).not.toHaveBeenCalled()
    await fireEvent.press(screen.getByRole("button", { name: "Yes, delete" }))
    await waitFor(() => expect(mockApi.deleteComment).toHaveBeenCalledWith(1))
    await waitFor(() => expect(screen.queryByText("Body 1")).toBeNull())
  })

  it("reports a comment with an optional reason and thanks the reporter", async () => {
    signedIn()
    mockApi.getComments.mockResolvedValue(page([comment(2)]))
    mockApi.reportComment.mockResolvedValue(undefined)
    await render(<CommentsSection targetType="article" targetId={5} />)
    await fireEvent.press(await screen.findByRole("button", { name: "Report comment by User2" }))
    await fireEvent.changeText(screen.getByLabelText("Why are you reporting this comment?"), "spam")
    await fireEvent.press(screen.getByRole("button", { name: "Send" }))
    expect(mockApi.reportComment).toHaveBeenCalledWith(2, "spam")
    expect(await screen.findByText(/a moderator will take a look/)).toBeTruthy()
  })

  it("replies appear under their parent, and a removed parent leaves a placeholder", async () => {
    signedIn()
    mockApi.getComments.mockResolvedValue(
      page([
        comment(1, { removed: true, author: null, body: "", replies: [comment(2, { body: "A reply", parent_id: 1 })], reply_count: 1 }),
      ]),
    )
    await render(<CommentsSection targetType="article" targetId={5} />)
    expect(await screen.findByText("This comment was removed.")).toBeTruthy()
    expect(screen.getByText("A reply")).toBeTruthy()
  })

  it("loads more pages without duplicating comments", async () => {
    mockApi.getComments
      .mockResolvedValueOnce({ ...page([comment(1)], 2), total: 2, total_comments: 2 })
      .mockResolvedValueOnce({ ...page([comment(1), comment(2)], 2), page: 2 })
    await render(<CommentsSection targetType="article" targetId={5} />)
    await fireEvent.press(await screen.findByRole("button", { name: /Load more comments \(1\)/ }))
    expect(await screen.findByText("Body 2")).toBeTruthy()
    expect(screen.getAllByText("Body 1")).toHaveLength(1)
  })
})
