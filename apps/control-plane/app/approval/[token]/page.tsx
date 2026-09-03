import type { Metadata } from "next";
import { headers } from "next/headers";
import { ApprovalFlow } from "../../../components/approval/flow";

export const dynamic = "force-dynamic";
export const metadata: Metadata = {
  title: "Revisión de solicitud · Agents Factory",
  description: "Revisión privada de una solicitud autorizada.",
  robots: { index: false, follow: false, noarchive: true },
  referrer: "no-referrer",
};

// Static script with no interpolated inputs. Runs before hydration, strips the
// fragment from history and exposes a single-use in-memory handoff to the form.
const captureLink = `(()=>{let v=new URLSearchParams(location.hash.slice(1)).get('token')||'';history.replaceState(null,'','/approval/review');Object.defineProperty(window,'__afTakeApprovalLink',{configurable:true,value:()=>{const r=v;v='';return r;}});addEventListener('pagehide',()=>{v='';},{once:true});})();`;

export default async function ApprovalPage() {
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <main className="approval-shell" lang="es">
      <script nonce={nonce} dangerouslySetInnerHTML={{ __html: captureLink }} />
      <section className="approval-card" aria-labelledby="approval-title">
        <p className="eyebrow">Agents Factory · Revisión segura</p>
        <h1 id="approval-title">Revisar una solicitud</h1>
        <p>
          Solo la primera decisión válida será registrada. Este enlace no da
          acceso al panel administrativo.
        </p>
        <ApprovalFlow />
        <noscript>
          Activa JavaScript para verificar el enlace de forma segura. No envíes
          códigos por otros medios.
        </noscript>
        <footer className="approval-footer">
          No compartas el enlace ni el código de verificación.
        </footer>
      </section>
    </main>
  );
}
