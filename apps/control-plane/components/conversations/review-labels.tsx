import {
  exportConversationEvalDraft,
  saveConversationReview,
} from "../../app/actions";
import type {
  ConversationOverview,
  ReviewCategory,
  ReviewLabel,
} from "../../lib/conversations";

const categoryLabels: Record<ReviewCategory, string> = {
  AI_RESOLVED: "AI resolved",
  HUMAN_HANDOFF: "Human handoff",
  TOOL_FAILURE: "Tool failure",
  POLICY_VIOLATION: "Policy violation",
  COMPLAINT: "Complaint",
  HIGH_COST: "High-cost conversation",
  FLAGGED: "Flagged conversation",
};
const reviewLabels: Record<ReviewLabel, string> = {
  CORRECT: "Correct",
  INCORRECT: "Incorrect",
  UNSAFE: "Unsafe",
  KNOWLEDGE_PROBLEM: "Knowledge problem",
  INTEGRATION_PROBLEM: "Integration problem",
  MODEL_REASONING_PROBLEM: "Model reasoning problem",
};

export function ReviewLabels({
  categories,
  conversation,
  labels,
  tenantId,
}: {
  categories: ReviewCategory[];
  conversation: ConversationOverview;
  labels: ReviewLabel[];
  tenantId: string;
}) {
  const review = conversation.review;
  return (
    <section className="review-panel">
      <p className="eyebrow">Human review</p>
      <h3>Categories and labels</h3>
      <form action={saveConversationReview} className="review-form">
        <input name="tenantId" type="hidden" value={tenantId} />
        <input name="conversationId" type="hidden" value={conversation.id} />
        <input name="revision" type="hidden" value={review?.revision ?? 0} />
        <fieldset>
          <legend>Review categories</legend>
          {categories.map((category) => (
            <label key={category}>
              <input
                defaultChecked={review?.categories.includes(category)}
                name="categories"
                type="checkbox"
                value={category}
              />
              {categoryLabels[category]}
            </label>
          ))}
        </fieldset>
        <fieldset>
          <legend>Outcome labels</legend>
          {labels.map((label) => (
            <label key={label}>
              <input
                defaultChecked={review?.labels.includes(label)}
                name="labels"
                type="checkbox"
                value={label}
              />
              {reviewLabels[label]}
            </label>
          ))}
        </fieldset>
        <label>
          Reviewer note
          <textarea defaultValue={review?.note ?? ""} name="note" rows={3} />
        </label>
        <button type="submit">Save human review</button>
      </form>
      <form action={exportConversationEvalDraft} className="eval-export-form">
        <input name="tenantId" type="hidden" value={tenantId} />
        <input name="conversationId" type="hidden" value={conversation.id} />
        <label>
          Regression reason
          <input
            defaultValue="Reviewed failure for regression coverage"
            name="reason"
            required
          />
        </label>
        <button className="secondary-button" type="submit">
          Export anonymized Eval Runner v0 Draft
        </button>
      </form>
    </section>
  );
}

export { categoryLabels, reviewLabels };
