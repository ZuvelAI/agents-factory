import { expect, it } from "vitest";
import { contactTitle, contactDetails } from "../../lib/contact-identity";

it("shows the name with actual phone and optional username", () => {
  const contact = {
    customer_wa_id: "CO.123",
    contact_name: "Ana",
    contact_username: "ana.ventas",
    contact_phone_number: "+573000000001",
  };
  expect(contactTitle(contact)).toBe("Ana");
  expect(contactDetails(contact)).toBe("+573000000001 · @ana.ventas");
});

it("never formats an opaque routing ID as a telephone", () => {
  expect(contactTitle({ customer_wa_id: "1234567890123" })).toBe(
    "Contacto sin nombre",
  );
  expect(contactDetails({ customer_wa_id: "1234567890123" })).toBe(
    "Referencia WhatsApp: 1234567890123",
  );
  expect(
    contactTitle({
      customer_wa_id: "CO.123",
      contact_phone_number: "+573000000001",
    }),
  ).toBe("+573000000001");
  expect(
    contactTitle({ customer_wa_id: "CO.123", contact_username: "ana.ventas" }),
  ).toBe("@ana.ventas");
});
