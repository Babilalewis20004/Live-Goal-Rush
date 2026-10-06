// Shared Jest setup (Phase 5 mobile test harness).
//
// `expo-router`'s <Link asChild> clones its child with navigation props; in a
// component test there is no navigator, so it is replaced by a pass-through
// that renders the child and exposes the target for assertions.
jest.mock("expo-router", () => {
  const React = jest.requireActual<typeof import("react")>("react")
  return {
    Link: ({ children, href }: { children: import("react").ReactElement<Record<string, unknown>>; href: unknown }) =>
      React.cloneElement(children, { testHref: JSON.stringify(href) }),
    router: { push: jest.fn() },
    useLocalSearchParams: jest.fn(() => ({})),
  }
})
