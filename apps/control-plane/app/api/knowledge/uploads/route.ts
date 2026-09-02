import { BackendProblem, callAuthenticatedBackend } from "../../../../lib/api";

const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;

export async function PUT(request: Request): Promise<Response> {
  const contentLength = Number(request.headers.get("content-length"));
  if (
    !Number.isSafeInteger(contentLength) ||
    contentLength < 1 ||
    contentLength > MAX_UPLOAD_BYTES
  ) {
    return Response.json(
      { code: "knowledge_upload_size_invalid" },
      { status: 413 },
    );
  }
  const url = new URL(request.url);
  const tenantId = url.searchParams.get("tenantId");
  const sourceId = url.searchParams.get("sourceId");
  const uploadKey = url.searchParams.get("uploadKey");
  const mediaType = request.headers.get("content-type")?.split(";", 1)[0];
  if (!tenantId || !sourceId || !uploadKey || !mediaType) {
    return Response.json({ code: "knowledge_upload_invalid" }, { status: 422 });
  }
  const body = await request.arrayBuffer();
  if (body.byteLength !== contentLength || body.byteLength > MAX_UPLOAD_BYTES) {
    return Response.json(
      { code: "knowledge_upload_size_invalid" },
      { status: 413 },
    );
  }
  try {
    const result = await callAuthenticatedBackend(
      `/admin/tenants/${encodeURIComponent(tenantId)}/knowledge/sources/${encodeURIComponent(sourceId)}/uploads/${encodeURIComponent(uploadKey)}`,
      { method: "PUT", headers: { "Content-Type": mediaType }, body },
    );
    return Response.json(result, { status: 201 });
  } catch (error) {
    const status = error instanceof BackendProblem ? error.status : 502;
    const code =
      error instanceof BackendProblem ? error.code : "knowledge_upload_failed";
    return Response.json({ code }, { status });
  }
}
