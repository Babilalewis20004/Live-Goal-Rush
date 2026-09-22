import { Ionicons } from "@expo/vector-icons"
import { useState } from "react"
import { Pressable, StyleSheet } from "react-native"

import { useAuth } from "@/hooks/use-auth"
import { api } from "@/lib/api"
import { theme } from "@/theme"

type FavouriteKind = "team" | "competition" | "match"

const FOLLOW: Record<FavouriteKind, (id: number) => Promise<void>> = {
  team: api.followTeam,
  competition: api.followCompetition,
  match: api.followMatch,
}

const UNFOLLOW: Record<FavouriteKind, (id: number) => Promise<void>> = {
  team: api.unfollowTeam,
  competition: api.unfollowCompetition,
  match: api.unfollowMatch,
}

/** Mirrors the web `FavouriteButton` (Phase 3 §29): only rendered on
 * detail screens that already know the entity's follow-state, hidden for
 * a logged-out visitor rather than prompting login. */
export function FavouriteButton({
  kind,
  id,
  initialFollowed,
}: {
  kind: FavouriteKind
  id: number
  initialFollowed: boolean
}) {
  const { user } = useAuth()
  const [followed, setFollowed] = useState(initialFollowed)
  const [pending, setPending] = useState(false)

  if (!user) return null

  async function toggle() {
    if (pending) return
    setPending(true)
    const next = !followed
    setFollowed(next)
    try {
      await (next ? FOLLOW[kind](id) : UNFOLLOW[kind](id))
    } catch {
      setFollowed(!next)
    } finally {
      setPending(false)
    }
  }

  return (
    <Pressable onPress={toggle} disabled={pending} style={[styles.button, followed && styles.buttonActive]}>
      <Ionicons name={followed ? "star" : "star-outline"} size={18} color={followed ? theme.amber : theme.textFaint} />
    </Pressable>
  )
}

const styles = StyleSheet.create({
  button: {
    width: 36,
    height: 36,
    borderRadius: 10,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: theme.border,
    backgroundColor: theme.card,
    alignItems: "center",
    justifyContent: "center",
  },
  buttonActive: {
    borderColor: "rgba(251,191,36,0.4)",
    backgroundColor: "rgba(251,191,36,0.1)",
  },
})
