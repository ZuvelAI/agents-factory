import "server-only";

import { callAuthenticatedBackend } from "./api";
import { isCoexistenceSignupEnabled } from "./whatsapp-mode";

export async function getCoexistenceSignupAvailability(
  tenantId: string,
): Promise<boolean> {
  const controller = new AbortController();
  let timeout: ReturnType<typeof setTimeout> | undefined;
  try {
    const result = await Promise.race([
      callAuthenticatedBackend<unknown>(
        `/admin/tenants/${encodeURIComponent(tenantId)}/whatsapp/signup/availability`,
        { signal: controller.signal },
      ),
      new Promise<null>((resolve) => {
        // Bound authentication as well as fetch; abort alone cannot bound both.
        timeout = setTimeout(() => {
          controller.abort();
          resolve(null);
        }, 2_000);
      }),
    ]);
    return isCoexistenceSignupEnabled(result);
  } catch {
    return false;
  } finally {
    clearTimeout(timeout);
  }
}
