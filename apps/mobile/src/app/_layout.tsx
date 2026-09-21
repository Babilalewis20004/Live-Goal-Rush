import { Stack } from "expo-router"
import { StatusBar } from "expo-status-bar"
import { theme } from "@/theme"

export default function RootLayout() {
  return (
    <>
      <StatusBar style="light" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: theme.background },
          headerTintColor: theme.text,
          headerShadowVisible: false,
          contentStyle: { backgroundColor: theme.background },
        }}
      >
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="match/[id]" options={{ title: "Match" }} />
        <Stack.Screen name="competition/[id]" options={{ title: "Competition" }} />
        <Stack.Screen name="team/[id]" options={{ title: "Team" }} />
      </Stack>
    </>
  )
}
