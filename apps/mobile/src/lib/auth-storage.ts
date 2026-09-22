import * as SecureStore from "expo-secure-store"

// Access + refresh tokens are the only sensitive data this app persists
// (Phase 3 §26) -- expo-secure-store backs onto Keychain (iOS) / Keystore
// (Android), never plain AsyncStorage.
const ACCESS_TOKEN_KEY = "livepitch.access_token"
const REFRESH_TOKEN_KEY = "livepitch.refresh_token"

export async function getStoredAccessToken(): Promise<string | null> {
  return SecureStore.getItemAsync(ACCESS_TOKEN_KEY)
}

export async function getStoredRefreshToken(): Promise<string | null> {
  return SecureStore.getItemAsync(REFRESH_TOKEN_KEY)
}

export async function storeTokens(accessToken: string, refreshToken: string): Promise<void> {
  await Promise.all([
    SecureStore.setItemAsync(ACCESS_TOKEN_KEY, accessToken),
    SecureStore.setItemAsync(REFRESH_TOKEN_KEY, refreshToken),
  ])
}

export async function clearTokens(): Promise<void> {
  await Promise.all([
    SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY),
    SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY),
  ])
}
