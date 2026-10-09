import Constants, { ExecutionEnvironment } from "expo-constants"
import * as Device from "expo-device"
import { router } from "expo-router"
import { Platform } from "react-native"

import { ApiError, api } from "@/lib/api"
import { hrefForNotification } from "@/lib/deep-links"

type NotificationsModule = typeof import("expo-notifications")

/** Remote push was removed from Expo Go (SDK 53+), and merely *importing*
 * `expo-notifications` there throws on Android -- which used to crash the
 * whole app at start-up, since this file is imported by the auth provider.
 * So the module is loaded lazily, and never in Expo Go; a development build
 * (or a production build) gets the full behaviour. */
const isExpoGo = Constants.executionEnvironment === ExecutionEnvironment.StoreClient

let notificationsPromise: Promise<NotificationsModule | null> | null = null

function loadNotifications(): Promise<NotificationsModule | null> {
  if (isExpoGo) return Promise.resolve(null)
  if (!notificationsPromise) {
    notificationsPromise = import("expo-notifications")
      .then((module) => {
        module.setNotificationHandler({
          handleNotification: async () => ({
            shouldShowAlert: true,
            shouldPlaySound: false,
            shouldSetBadge: false,
            shouldShowBanner: true,
            shouldShowList: true,
          }),
        })
        return module
      })
      .catch((error) => {
        console.warn("Push notifications unavailable:", error)
        return null
      })
  }
  return notificationsPromise
}

/** Called once, after login succeeds (Phase 3 §17) -- an anonymous user
 * has no `Device` row to attach a token to. Degrades gracefully (logs and
 * returns) rather than throwing whenever push isn't actually available in
 * this environment: Expo Go, no physical device, no notification permission,
 * or this Expo project not yet linked to an EAS project -- that one-time
 * `expo.dev` account step is outside what a code change can do. */
export async function registerForPushNotificationsAsync(): Promise<void> {
  if (!Device.isDevice) {
    return
  }

  const Notifications = await loadNotifications()
  if (!Notifications) {
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
 * the unsubscribe function for cleanup (a no-op where push isn't available). */
export function addNotificationResponseListener(): () => void {
  let unsubscribe: (() => void) | null = null
  let cancelled = false

  void loadNotifications().then((Notifications) => {
    if (!Notifications || cancelled) return
    const subscription = Notifications.addNotificationResponseReceivedListener((response) => {
      // Allow-listed screens only (match/team/competition/player/article).
      const href = hrefForNotification(response.notification.request.content.data as { type?: unknown; id?: unknown })
      if (href) router.push(href as Parameters<typeof router.push>[0])
    })
    unsubscribe = () => subscription.remove()
  })

  return () => {
    cancelled = true
    unsubscribe?.()
  }
}
