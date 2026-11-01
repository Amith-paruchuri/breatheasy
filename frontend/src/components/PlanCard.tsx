import { useState } from "react";
import * as api from "../api";
import { useAccount } from "../account";
import type { PlansConfig } from "../types";

declare global {
  interface Window {
    Razorpay?: new (opts: Record<string, unknown>) => { open: () => void; on: (e: string, cb: (r: unknown) => void) => void };
  }
}

function loadCheckout(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("The payment window couldn't load. Check your connection and try again."));
    document.head.appendChild(s);
  });
}

function fmtDay(iso: string) {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

/** Plan, street-level searches left this month, and the upgrade to Breatheasy Plus. */
export function PlanCard({ plans }: { plans: PlansConfig }) {
  const { plan, reload } = useAccount();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  if (!plans.enabled || !plan) return null;
  const plus = plan.plan === "plus";
  const left = Math.max(0, plan.limit - plan.used);

  async function upgrade(period: "monthly" | "yearly") {
    setBusy(true);
    setMsg(null);
    try {
      await loadCheckout();
      const sub = await api.subscribe(period);
      await new Promise<void>((resolve, reject) => {
        const rz = new window.Razorpay!({
          key: sub.key_id,
          subscription_id: sub.subscription_id,
          name: "Breatheasy Plus",
          description: period === "monthly" ? "Monthly plan" : "Yearly plan",
          prefill: { name: sub.name, email: sub.email },
          theme: { color: "#4338ca" },
          modal: { ondismiss: () => reject(new Error("")) },
          handler: async (r: { razorpay_payment_id: string; razorpay_subscription_id: string; razorpay_signature: string }) => {
            try {
              await api.verifyPayment({ ...r, period });
              resolve();
            } catch (e) {
              reject(e);
            }
          },
        });
        rz.on("payment.failed", () => reject(new Error("The payment didn't go through. You haven't been charged.")));
        rz.open();
      });
      await reload();
      setMsg("Welcome to Breatheasy Plus.");
    } catch (e) {
      const m = (e as Error).message;
      if (m) setMsg(m);
    } finally {
      setBusy(false);
    }
  }

  async function cancel() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await api.cancelPlus();
      setMsg(r.plus_until ? `Renewal cancelled. Plus stays on until ${fmtDay(r.plus_until)}.` : "Renewal cancelled.");
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`plan-card${plus ? " is-plus" : ""}`}>
      <div className="plan-top">
        <strong>{plus ? "Breatheasy Plus" : "Free plan"}</strong>
        {plus && plan.plus_until && <span>Renews or ends {fmtDay(plan.plus_until)}</span>}
      </div>
      <div className="plan-meter" role="meter" aria-valuemin={0} aria-valuemax={plan.limit} aria-valuenow={plan.used} aria-label="Street-level searches used this month">
        <i style={{ width: `${Math.min(100, (plan.used / Math.max(1, plan.limit)) * 100)}%` }} />
      </div>
      <p className="plan-line">
        {left} of {plan.limit} street-level searches left this month. After that, searches use open data (coarser air, still free).
      </p>
      {!plus && plans.payments && (
        <div className="plan-actions">
          {plans.monthly_inr != null && (
            <button type="button" className="btn-primary" disabled={busy} onClick={() => upgrade("monthly")}>
              Get Plus · ₹{plans.monthly_inr}/month
            </button>
          )}
          {plans.yearly_inr != null && (
            <button type="button" className="chip" disabled={busy} onClick={() => upgrade("yearly")}>
              ₹{plans.yearly_inr}/year
            </button>
          )}
          <p className="fine">Plus: street-level air on {plans.plus_street_searches} searches a month. Cancel anytime; payments by Razorpay.</p>
        </div>
      )}
      {plus && plans.payments && (
        <button type="button" className="text-btn" disabled={busy} onClick={cancel}>
          Cancel renewal
        </button>
      )}
      {msg && <p className="sheet-msg" role="status">{msg}</p>}
    </div>
  );
}
