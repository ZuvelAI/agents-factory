import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import {
  ConfigurationFields,
  type FieldDefinition,
} from "../../components/agent-workspace/configuration-fields";

function renderField(field: FieldDefinition) {
  return renderToStaticMarkup(
    createElement(ConfigurationFields, {
      prefix: "test",
      fields: [field],
      value: { [field.key]: null },
      onChange: () => {},
    }),
  );
}

it("does not offer an empty value for required choices", () => {
  const html = renderField({
    key: "tone",
    label: "Tono",
    options: ["FRIENDLY"],
  });
  expect(html).not.toContain('value=""');
});

it("does not offer an empty value for required booleans", () => {
  const html = renderField({
    key: "review_confirmed",
    label: "Revisado",
    kind: "boolean",
  });
  expect(html).not.toContain('value=""');
  expect(html).toContain('value="false"');
  expect(html).toContain('value="true"');
});

it("allows an empty value only for explicitly nullable fields", () => {
  for (const field of [
    {
      key: "pricing_response",
      label: "Precios",
      options: ["QUOTE_REQUIRED"],
      nullable: true,
    },
    {
      key: "handoff_enabled",
      label: "Derivación",
      kind: "boolean" as const,
      nullable: true,
    },
  ]) {
    expect(renderField(field)).toContain('value=""');
  }
});

it("keeps the explicit NOT_DEFINED enum distinct from an empty value", () => {
  const html = renderField({
    key: "privacy_policy_status",
    label: "Privacidad",
    options: ["NOT_DEFINED"],
  });
  expect(html).toContain('value="NOT_DEFINED"');
  expect(html).not.toContain('value=""');
});
