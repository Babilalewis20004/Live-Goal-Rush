import { describe, expect, it } from "vitest"

import { EMPTY_FIELDS, buildInput, parseTags, validateFields, validatePublish } from "@/lib/editor"

describe("editor helpers", () => {
  it("parses tags like the API will accept them", () => {
    expect(parseTags("Real Madrid, transfer ,real  madrid,, ")).toEqual(["Real Madrid", "transfer"])
    expect(parseTags("")).toEqual([])
    expect(parseTags(Array.from({ length: 15 }, (_, i) => `tag${i}`).join(","))).toHaveLength(10)
    expect(parseTags("x".repeat(80))[0]).toHaveLength(50)
  })

  it("builds the payload, clearing optional fields explicitly", () => {
    const input = buildInput({
      ...EMPTY_FIELDS,
      title: "  Derby day  ",
      tags: "A, B",
      entities: {
        ...EMPTY_FIELDS.entities,
        teams: [{ id: 3, name: "Arsenal", short_name: null, country: null, logo_url: null }],
      },
    })
    expect(input.title).toBe("Derby day")
    expect(input.tags).toEqual(["A", "B"])
    expect(input.team_ids).toEqual([3])
    expect(input.featured_image_url).toBeNull()
    expect(input.featured_image_alt).toBeNull()
    expect(input.category_id).toBeNull()
  })

  it("drops the alt text when there is no image", () => {
    expect(buildInput({ ...EMPTY_FIELDS, title: "abc", imageAlt: "stale" }).featured_image_alt).toBeNull()
    expect(
      buildInput({ ...EMPTY_FIELDS, title: "abc", imageUrl: "https://x.example/a.jpg", imageAlt: "A goal" }).featured_image_alt,
    ).toBe("A goal")
  })

  it("explains what is missing before saving or publishing", () => {
    expect(validateFields(EMPTY_FIELDS)).toMatch(/title/)
    expect(validateFields({ ...EMPTY_FIELDS, title: "Fine title", imageUrl: "javascript:alert(1)" })).toMatch(/http/)
    expect(validateFields({ ...EMPTY_FIELDS, title: "Fine title" })).toBeNull()
    expect(validatePublish({ ...EMPTY_FIELDS, title: "Fine title" })).toMatch(/content/)
    expect(validatePublish({ ...EMPTY_FIELDS, title: "Fine title", content: "<p> </p>" })).toMatch(/content/)
    expect(validatePublish({ ...EMPTY_FIELDS, title: "Fine title", content: "<p>Hello</p>" })).toBeNull()
  })
})
