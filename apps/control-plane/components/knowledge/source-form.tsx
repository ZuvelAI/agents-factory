"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

import {
  createKnowledgeSource,
  createKnowledgeUploadSource,
  startKnowledgeSourceIngestion,
} from "../../app/actions";
import type {
  KnowledgeAuthority,
  KnowledgeSourceType,
} from "../../lib/knowledge";

export function SourceForm({ tenantId }: { tenantId: string }) {
  const router = useRouter();
  const [sourceType, setSourceType] = useState<KnowledgeSourceType>("WEBSITE");
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    if (!isUploadType(sourceType)) return;
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const file = form.get("sourceFile");
    const name = form.get("name");
    const authority = form.get("authority");
    if (
      !(file instanceof File) ||
      file.size < 1 ||
      file.size > 20 * 1024 * 1024 ||
      typeof name !== "string" ||
      !name.trim() ||
      typeof authority !== "string"
    ) {
      setUploadError("Choose a valid source file of 20 MB or less.");
      return;
    }
    setUploading(true);
    setUploadError(null);
    const created = await createKnowledgeUploadSource({
      tenantId,
      name,
      sourceType,
      authority: authority as KnowledgeAuthority,
    });
    if (!created.ok) {
      setUploadError(created.message);
      setUploading(false);
      return;
    }
    const query = new URLSearchParams({
      tenantId,
      sourceId: created.data.sourceId,
      uploadKey: created.data.uploadKey,
    });
    const upload = await fetch(`/api/knowledge/uploads?${query}`, {
      method: "PUT",
      headers: { "Content-Type": created.data.mediaType },
      body: file,
    });
    if (!upload.ok) {
      setUploadError("The private source file could not be uploaded.");
      setUploading(false);
      return;
    }
    const started = await startKnowledgeSourceIngestion({
      tenantId,
      sourceId: created.data.sourceId,
    });
    if (!started.ok) {
      setUploadError(started.message);
      setUploading(false);
      return;
    }
    setUploading(false);
    router.push(`/tenants/${tenantId}/knowledge?saved=source`);
    router.refresh();
  }

  return (
    <form
      action={createKnowledgeSource}
      className="knowledge-source-form form-section"
      onSubmit={submit}
    >
      <input name="tenantId" type="hidden" value={tenantId} />
      <div>
        <p className="eyebrow">Source intake</p>
        <h3>Add a business source</h3>
        <p>
          Every source is synchronized into a human review queue. Nothing is
          published automatically.
        </p>
      </div>
      <div className="form-grid">
        <label>
          Source name
          <input name="name" required />
        </label>
        <label>
          Source type
          <select
            name="sourceType"
            onChange={(event) =>
              setSourceType(event.target.value as KnowledgeSourceType)
            }
            value={sourceType}
          >
            <option value="WEBSITE">Website</option>
            <option value="PDF">PDF</option>
            <option value="DOCX">Word document</option>
            <option value="GOOGLE_DRIVE">Google Drive</option>
            <option value="SPREADSHEET">Spreadsheet</option>
            <option value="MANUAL">Manual entry</option>
          </select>
        </label>
        <label>
          Authority
          <select defaultValue="REFERENCE" name="authority">
            <option value="AUTHORITATIVE">Authoritative</option>
            <option value="SECONDARY">Secondary</option>
            <option value="REFERENCE">Reference</option>
          </select>
          <span>Authority is fixed when a proposal is reviewed.</span>
        </label>
        <SourceInput sourceType={sourceType} />
      </div>
      {uploadError ? <p role="alert">{uploadError}</p> : null}
      <div className="form-actions">
        <button disabled={uploading} type="submit">
          {uploading
            ? "Uploading private source…"
            : "Add source and synchronize"}
        </button>
      </div>
    </form>
  );
}

function isUploadType(
  sourceType: KnowledgeSourceType,
): sourceType is "PDF" | "DOCX" | "SPREADSHEET" {
  return ["PDF", "DOCX", "SPREADSHEET"].includes(sourceType);
}

function SourceInput({ sourceType }: { sourceType: KnowledgeSourceType }) {
  if (sourceType === "WEBSITE") {
    return (
      <label>
        HTTPS address
        <input
          name="url"
          placeholder="https://example.com/help"
          required
          type="url"
        />
      </label>
    );
  }
  if (sourceType === "GOOGLE_DRIVE") {
    return (
      <label>
        Google Drive file ID
        <input name="googleDriveFileId" required />
      </label>
    );
  }
  if (sourceType === "MANUAL") {
    return (
      <label className="full-width-field">
        Approved business content
        <textarea name="manualContent" required rows={5} />
      </label>
    );
  }
  const accept = {
    PDF: "application/pdf,.pdf",
    DOCX: "application/vnd.openxmlformats-officedocument.wordprocessingml.document,.docx",
    SPREADSHEET:
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,.xlsx",
  }[sourceType];
  return (
    <label>
      Private source file
      <input accept={accept} name="sourceFile" required type="file" />
      <span>Maximum 20 MB. The original remains in private storage.</span>
    </label>
  );
}
