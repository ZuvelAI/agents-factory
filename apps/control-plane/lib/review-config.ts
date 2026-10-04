import "server-only";

export type ReviewBinding = {
  tenantId: string;
  accountId: string;
  wabaId: string;
  phoneNumberId: string;
  recipient: string;
};

export function getReviewBinding(): ReviewBinding | null {
  const tenantId = process.env.META_REVIEW_TENANT_ID;
  const accountId = process.env.META_REVIEW_ACCOUNT_ID;
  const wabaId = process.env.META_REVIEW_WABA_ID;
  const phoneNumberId = process.env.META_REVIEW_PHONE_NUMBER_ID;
  const recipient = process.env.META_REVIEW_RECIPIENT;
  const uuid =
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
  const assetId = /^[0-9]{1,64}$/;
  if (
    !tenantId ||
    !accountId ||
    !wabaId ||
    !phoneNumberId ||
    !recipient ||
    !uuid.test(tenantId) ||
    !uuid.test(accountId) ||
    !assetId.test(wabaId) ||
    !assetId.test(phoneNumberId) ||
    !/^[1-9][0-9]{7,14}$/.test(recipient)
  )
    return null;
  return {
    tenantId: tenantId.toLowerCase(),
    accountId: accountId.toLowerCase(),
    wabaId,
    phoneNumberId,
    recipient,
  };
}
