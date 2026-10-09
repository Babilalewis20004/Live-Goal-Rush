import { Stack } from "expo-router"
import { StatusBar } from "expo-status-bar"
import { useEffect } from "react"
import { AuthProvider } from "@/hooks/use-auth"
import { addNotificationResponseListener } from "@/lib/push-notifications"
import { theme } from "@/theme"

function NotificationTapHandler() {
  useEffect(() => addNotificationResponseListener(), [])
  return null
}

export default function RootLayout() {
  return (
    <AuthProvider>
      <StatusBar style="light" />
      <NotificationTapHandler />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: theme.background },
          headerTintColor: theme.text,
          headerShadowVisible: false,
          contentStyle: { backgroundColor: theme.background },
        }}
      >
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
        <Stack.Screen name="article/[slug]" options={{ title: "News" }} />
        <Stack.Screen name="poll/[id]" options={{ title: "Poll" }} />
        <Stack.Screen name="u/[id]" options={{ title: "Profile" }} />
        <Stack.Screen name="editor/index" options={{ title: "Articles" }} />
        <Stack.Screen name="editor/[id]" options={{ title: "Article" }} />
        <Stack.Screen name="match/[id]" options={{ title: "Match" }} />
        <Stack.Screen name="competition/[id]" options={{ title: "Competition" }} />
        <Stack.Screen name="team/[id]" options={{ title: "Team" }} />
        <Stack.Screen name="player/[id]" options={{ title: "Player" }} />
        <Stack.Screen name="login" options={{ title: "Log in", presentation: "modal" }} />
        <Stack.Screen name="register" options={{ title: "Create account", presentation: "modal" }} />
        <Stack.Screen name="favourites" options={{ title: "Favourites" }} />
        <Stack.Screen name="notification-settings" options={{ title: "Notification Settings" }} />
      </Stack>
    </AuthProvider>
  )
}
