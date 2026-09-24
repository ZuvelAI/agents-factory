"use client";
import { useState } from "react";
import { reviewTemplates, reviewSend } from "./actions";

export function ReviewPanel() {
  const [templates, setTemplates] = useState<{ name: string; language: string }[]>([]);
  const [selected, setSelected] = useState("0");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  return <section>
    <h2>Approved templates</h2>
    <button disabled={busy} onClick={async () => {
      setBusy(true);
      try {
        const result = await reviewTemplates();
        if (result.ok) { setTemplates(result.data); setSelected("0"); setMessage(`${result.data.length} approved templates loaded from Meta.`); }
        else setMessage(result.message);
      } finally { setBusy(false); }
    }}>Load templates from Meta</button>
    <p><label>Template <select value={selected} onChange={e => setSelected(e.target.value)} disabled={busy || !templates.length}>
      {!templates.length && <option value="0">Load templates first</option>}
      {templates.map((t, i) => <option key={`${t.name}:${t.language}`} value={i}>{t.name} — {t.language}</option>)}
    </select></label></p>
    <h2>Test message</h2>
    <p>Messages go only to the owner's registered test recipient ending in 8756, not to the reviewer's phone. Delivery is demonstrated in the submitted video. Maximum 10 test messages per day.</p>
    <button disabled={busy || !templates[Number(selected)]} onClick={async () => {
      const template = templates[Number(selected)];
      if (!template) return;
      setBusy(true);
      try {
        const result = await reviewSend(template.name, template.language, crypto.randomUUID());
        setMessage(result.ok ? `Submitted to the outbound queue. Message ID: ${result.data.id}. This is not a delivery confirmation.` : result.message);
      } finally { setBusy(false); }
    }}>Send test message to registered recipient</button>
    <p role="status">{message}</p>
  </section>;
}
