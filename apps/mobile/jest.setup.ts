// Shared Jest setup (Phase 5 mobile test harness).
//
// `expo-router`'s <Link asChild> clones its child with navigation props; in a
// component test there is no navigator, so it is replaced by a pass-through
// that renders the child and exposes the target for assertions.
jest.mock("expo-router", () => {
  const React = jest.requireActual<typeof import("react")>("react")
  return {
    Link: ({ children, href, style }: { children: import("react").ReactNode; href: unknown; style?: never }) => {
      const testHref = JSON.stringify(href)
      if (React.isValidElement(children)) return React.cloneElement(children as never, { testHref } as never)
      const { Text } = jest.requireActual<typeof import("react-native")>("react-native")
      return React.createElement(Text, { testHref, style } as never, children)
    },
    router: { push: jest.fn() },
    useLocalSearchParams: jest.fn(() => ({})),
  }
})

// Phase 7: the on-device cache uses AsyncStorage; tests get the in-memory implementation it ships for Jest.
jest.mock("@react-native-async-storage/async-storage", () =>
  jest.requireActual("@react-native-async-storage/async-storage/jest/async-storage-mock"),
)
