import { View } from "react-native"

import { CommentsSection } from "@/components/community/comments-section"
import { PollsFor } from "@/components/community/poll-card"
import { ReactionsBar } from "@/components/community/reactions-bar"
import type { CommentTargetType } from "@/types/api"

/** Reactions, polls and comments for one article or match, in that order. */
export function Discuss({ targetType, targetId }: { targetType: CommentTargetType; targetId: number }) {
  return (
    <View style={{ gap: 20 }}>
      <ReactionsBar targetType={targetType} targetId={targetId} />
      <PollsFor {...(targetType === "match" ? { matchId: targetId } : { articleId: targetId })} />
      <CommentsSection targetType={targetType} targetId={targetId} />
    </View>
  )
}
