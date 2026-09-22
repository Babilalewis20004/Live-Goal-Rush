import Constants from "expo-constants"
import * as Device from "expo-device"
import * as Notifications from "expo-notifications"
import { router } from "expo-router"
import { Platform } from "react-native"

import { ApiError, api } from "@/lib/api"

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: false,
    shouldSetBadge: false,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
})

/** Called once, after login succeeds (Phase 3 §17) -- an anonymous user
 * has no `Device` row to attach a token to. Degrades gracefully (logs and
 * returns) rather than throwing whenever push isn't actually available in
 * this environment: no physical device, no notification permission, or
 * (most likely here) this Expo project not yet linked to an EAS project --
 * that one-time `expo.dev` account step is outside what a code change can
 * do, exactly like this repo already ships `RealFootballDataProvider`
 * behind an interface without real API credentials configured. */
export async function registerForPushNotificationsAsync(): Promise<void> {
  if (!Device.isDevice) {
    return
  }

  const projectId = Constants.expoConfig?.extra?.eas?.projectId as string | undefined
  if (!projectId) {
    console.warn("Push notifications unavailable: this Expo project has no EAS projectId configured.")
    return
  }

  const { status: existingStatus } = await Notifications.getPermissionsAsync()
  let finalStatus = existingStatus
  if (existingStatus !== "granted") {
    const { status } = await Notifications.requestPermissionsAsync()
    finalStatus = status
  }
  if (finalStatus !== "granted") {
    return
  }

  if (Platform.OS === "android") {
    await Notifications.setNotificationChannelAsync("default", {
      name: "default",
      importance: Notifications.AndroidImportance.DEFAULT,
    })
  }

  try {
    const { data: expoPushToken } = await Notifications.getExpoPushTokenAsync({ projectId })
    await api.registerDevice({
      platform: Platform.OS === "ios" ? "expo_ios" : "expo_android",
      expo_push_token: expoPushToken,
    })
  } catch (error) {
    console.warn("Failed to register push token:", error instanceof ApiError ? error.message : error)
  }
}

/** Tap handling (Phase 3 §17): reads the same `{type, id}` deep-link
 * payload the backend's `NotificationService` and the web service worker
 * both use, and navigates using the existing Expo Router paths -- no new
 * navigation structure needed. Call once from the root layout; returns
 * the unsubscribe function for cleanup. */
export function addNotificationResponseListener(): () => void {
  const subscription = Notifications.addNotificationResponseReceivedListener((response) => {
    const data = response.notification.request.content.data as
      | { type?: string; id?: number | string }
      | undefined
    if (data?.type && data.id != null) {
      router.push(`/${data.type}/${data.id}` as Parameters<typeof router.push>[0])
    }
  })
  return () => subscription.remove()
}
